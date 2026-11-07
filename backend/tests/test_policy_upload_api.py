
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
    PolicyDocumentApplicability,
)
from claimsage.db.session import SessionLocal
from claimsage.schemas.policies import PolicyDocumentApplicability as Applicability
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
        applicability: Applicability | None = None,
        source_url: str | None = None,
        **kwargs,
    ):
        document = PolicyDocument(
            filename=filename or Path(file_path).name,
            checksum_sha256=uuid4().hex + uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=Path(file_path).stat().st_size,
            source_url=source_url,
            storage_provider=kwargs.get("storage_provider"),
            storage_bucket=kwargs.get("storage_bucket"),
            storage_key=kwargs.get("storage_key"),
            storage_status=kwargs.get("storage_status"),
            insurer_name=(
                applicability.insurer_name
                if applicability is not None
                else None
            ),
            product_name=(
                applicability.product_name
                if applicability is not None
                else None
            ),
            uploaded_by_employee_id=uploader_employee_id,
            policy_identifier=(
                applicability.policy_identifier
                if applicability is not None
                else None
            ),
            insurance_type=(
                applicability.insurance_type
                if applicability is not None
                else None
            ),
            policy_version=(
                applicability.policy_version
                if applicability is not None
                else None
            ),
            effective_from=(
                applicability.effective_from
                if applicability is not None
                else None
            ),
            effective_to=(
                applicability.effective_to
                if applicability is not None
                else None
            ),
            status="uploaded",
        )

        db.add(document)
        db.flush()

        if applicability is not None:
            db.add_all(
                PolicyDocumentApplicability(
                    document_id=document.id,
                    claim_type=claim_type,
                )
                for claim_type in applicability.supported_claim_types
            )

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

    def fake_embed(db, *, document_id):
        document = db.get(PolicyDocument, document_id)
        document.status = "processed"
        db.commit()
        return document

    monkeypatch.setattr(
        policy_routes,
        "process_policy_document_embeddings",
        fake_embed,
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
    assert body["status"] == "ready"
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

def test_policy_upload_requires_access_manager_for_applicability_metadata(
    client: TestClient,
    upload_employee: dict,
) -> None:
    headers = authorization_headers(client, upload_employee["email"])
    response = client.post(
        UPLOAD_URL,
        headers=headers,
        data={
            "supported_claim_types": "property",
            "policy_identifier": "POLICY-PROPERTY-001",
        },
        files={
            "file": (
                "property-policy.pdf",
                b"%PDF-1.4 synthetic policy",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 403


def test_policy_upload_persists_admin_supplied_applicability(
    client: TestClient,
    claims_scenario: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_persistence(monkeypatch)
    headers = authorization_headers(client, claims_scenario["admin_email"])
    try:
        response = client.post(
            UPLOAD_URL,
            headers=headers,
            data={
                "supported_claim_types": ["Property", "AUTO"],
                "policy_identifier": "POLICY-MULTI-001",
                "insurer_name": "Synthetic Assurance",
                "product_name": "Synthetic Property Cover",
                "insurance_type": "Property",
                "policy_version": "synthetic-2026-v1",
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "source_url": "https://policy.example.test/source.pdf",
            },
            files={
                "file": (
                    "multi-line-policy.pdf",
                    b"%PDF-1.4 synthetic policy",
                    "application/pdf",
                )
            },
        )

        assert response.status_code == 201
        response_body = response.json()
        assert response_body["insurer_name"] == "Synthetic Assurance"
        assert response_body["product_name"] == "Synthetic Property Cover"
        assert response_body["source_url"] == (
            "https://policy.example.test/source.pdf"
        )
        with SessionLocal() as session:
            document = session.get(
                PolicyDocument,
                response.json()["document_id"],
            )
            assert document is not None
            assert document.policy_identifier == "POLICY-MULTI-001"
            assert document.insurer_name == "Synthetic Assurance"
            assert document.product_name == "Synthetic Property Cover"
            assert document.source_url == "https://policy.example.test/source.pdf"
            assert document.insurance_type == "property"
            assert document.policy_version == "synthetic-2026-v1"
            assert document.effective_from.isoformat() == "2026-01-01"
            assert document.effective_to.isoformat() == "2026-12-31"
            assert {
                entry.claim_type for entry in document.supported_claim_types
            } == {"property", "auto"}
    finally:
        with SessionLocal.begin() as session:
            admin = session.scalar(
                select(Employee).where(
                    Employee.email == claims_scenario["admin_email"]
                )
            )
            if admin is not None:
                session.execute(
                    delete(PolicyDocument).where(
                        PolicyDocument.uploaded_by_employee_id == admin.id
                    )
                )


def test_policy_upload_rejects_partial_applicability_metadata(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    headers = authorization_headers(client, claims_scenario["admin_email"])
    response = client.post(
        UPLOAD_URL,
        headers=headers,
        data={"supported_claim_types": "property"},
        files={
            "file": (
                "property-policy.pdf",
                b"%PDF-1.4 synthetic policy",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422


def test_policy_upload_rejects_oversized_content_length(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject oversized requests before multipart parsing or authentication."""

    from claimsage.main import app

    monkeypatch.setattr(app, "max_body_bytes", 100)

    response = client.post(
        UPLOAD_URL,
        headers={"Content-Length": "101"},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "Upload request exceeds the configured size limit."
    )


def test_policy_upload_rejects_oversized_streamed_body(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject oversized authenticated multipart uploads without Content-Length."""

    from claimsage.main import app

    monkeypatch.setattr(app, "max_body_bytes", 100)

    boundary = "claimsage-test-boundary"
    multipart_body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="policy.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + (b"A" * 200) + f"\r\n--{boundary}--\r\n".encode()

    def oversized_body():
        yield multipart_body[:80]
        yield multipart_body[80:]

    headers = authorization_headers(client, upload_employee["email"])
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    response = client.post(
        UPLOAD_URL,
        content=oversized_body(),
        headers=headers,
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "Upload request exceeds the configured size limit."
    )
