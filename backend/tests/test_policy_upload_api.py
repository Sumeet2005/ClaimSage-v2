
"""Integration tests for authenticated policy document uploads."""

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from claimsage.api.routes import policies as policy_routes
from claimsage.db.models import (
    AuditEvent,
    Employee,
    PolicyChunk,
    PolicyDocument,
)
from claimsage.db.session import SessionLocal
from claimsage.services.document_persistence import (
    DocumentPersistenceError,
    DuplicatePolicyDocumentError,
)

UPLOAD_URL = "/api/v1/policies/documents"


@pytest.fixture
def upload_employee(claims_scenario: dict) -> Generator[dict, None, None]:
    """Provide an authenticated synthetic employee and clean up uploaded documents."""

    with SessionLocal() as session:
        employee = session.scalar(
            select(Employee).where(
                Employee.email == claims_scenario["adjuster_email"]
            )
        )
        assert employee is not None

        employee_id = employee.id
        email = employee.email

    try:
        yield {
            "id": employee_id,
            "email": email,
        }
    finally:
        # Delete policy documents before the parent fixture deletes employees.
        with SessionLocal.begin() as session:
            session.execute(
                delete(PolicyDocument).where(
                    PolicyDocument.uploaded_by_employee_id == employee_id
                )
            )


def authorization_headers(client: TestClient, email: str) -> dict[str, str]:
    """Return Bearer authorization headers for a synthetic employee."""

    from test_claim_access import login

    token = login(client, email)
    return {"Authorization": f"Bearer {token}"}


def install_fake_persistence(monkeypatch):
    """Replace PDF persistence with a deterministic database-backed test double."""

    def fake_persist(
        db,
        file_path: str | Path,
        uploader_employee_id,
        filename: str | None = None,
    ):
        document = PolicyDocument(
            filename=filename or Path(file_path).name,
            checksum_sha256=uuid4().hex + uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=Path(file_path).stat().st_size,
            uploaded_by_employee_id=uploader_employee_id,
            status="processed",
        )

        db.add(document)
        db.flush()

        db.add(
            PolicyChunk(
                document_id=document.id,
                page_number=1,
                chunk_index=0,
                chunk_id=uuid4().hex + uuid4().hex,
                text="Synthetic policy document text for API testing.",
            )
        )

        db.flush()
        return document

    monkeypatch.setattr(
        policy_routes,
        "persist_policy_document",
        fake_persist,
    )


def test_policy_upload_requires_authentication(client: TestClient) -> None:
    """Unauthenticated employees cannot upload policy documents."""

    response = client.post(
        UPLOAD_URL,
        files={"file": ("policy.pdf", b"synthetic content", "application/pdf")},
    )

    assert response.status_code == 401


def test_policy_upload_rejects_invalid_token(client: TestClient) -> None:
    """Invalid Bearer tokens cannot upload policy documents."""

    response = client.post(
        UPLOAD_URL,
        headers={"Authorization": "Bearer invalid-token"},
        files={"file": ("policy.pdf", b"synthetic content", "application/pdf")},
    )

    assert response.status_code == 401


def test_policy_upload_rejects_non_pdf(
    client: TestClient,
    upload_employee: dict,
) -> None:
    """Non-PDF filenames are rejected."""

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        files={"file": ("policy.txt", b"synthetic text", "text/plain")},
    )

    assert response.status_code == 415


def test_policy_upload_rejects_empty_file(
    client: TestClient,
    upload_employee: dict,
) -> None:
    """Empty PDF uploads are rejected."""

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400


def test_policy_upload_rejects_duplicate(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate document errors are returned as HTTP 409."""

    headers = authorization_headers(client, upload_employee["email"])

    def duplicate_document(**kwargs):
        raise DuplicatePolicyDocumentError(
            "A policy document with this content already exists."
        )

    monkeypatch.setattr(
        policy_routes,
        "persist_policy_document",
        duplicate_document,
    )

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        files={"file": ("policy.pdf", b"synthetic content", "application/pdf")},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "A policy document with this content already exists."
    )


def test_policy_upload_returns_422_when_processing_fails(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document processing failures do not create successful uploads."""

    headers = authorization_headers(client, upload_employee["email"])

    def fail_processing(**kwargs):
        raise DocumentPersistenceError("Synthetic processing failure.")

    monkeypatch.setattr(
        policy_routes,
        "persist_policy_document",
        fail_processing,
    )

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        files={"file": ("policy.pdf", b"synthetic content", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Synthetic processing failure."


def test_policy_upload_successfully_persists_document_and_audit_event(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful upload persists the document, chunks and audit event."""

    install_fake_persistence(monkeypatch)

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        files={
            "file": (
                "synthetic-policy.pdf",
                b"%PDF-1.4 synthetic test content",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["filename"] == "synthetic-policy.pdf"
    assert body["status"] == "processed"
    assert body["chunk_count"] == 1
    assert body["document_id"]

    with SessionLocal() as session:
        document = session.get(PolicyDocument, body["document_id"])

        assert document is not None
        assert document.uploaded_by_employee_id == upload_employee["id"]
        assert document.status == "processed"

        chunks = session.scalars(
            select(PolicyChunk).where(
                PolicyChunk.document_id == document.id
            )
        ).all()

        assert len(chunks) == 1

        audit_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(document.id),
                AuditEvent.action == "policy_document_uploaded",
            )
        )

        assert audit_event is not None
        assert audit_event.actor_employee_id == upload_employee["id"]
