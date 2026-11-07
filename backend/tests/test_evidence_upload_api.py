"""Integration tests for authenticated claim evidence uploads."""

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from claimsage.api.routes import evidence as evidence_routes
from claimsage.db.models import (
    AuditEvent,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
)
from claimsage.db.session import SessionLocal
from claimsage.rag.embedding_service import EmbeddingServiceError
from claimsage.services.evidence_persistence import (
    DuplicateClaimEvidenceError,
    EvidencePersistenceError,
)

UPLOAD_URL = "/api/v1/claims/{claim_id}/evidence"


@pytest.fixture
def upload_employee(claims_scenario: dict) -> Generator[dict, None, None]:
    """Provide an authenticated synthetic employee and clean up evidence."""

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
            "claim_id": claims_scenario["adjuster_claim_id"],
        }
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(ClaimEvidenceDocument).where(
                    ClaimEvidenceDocument.uploaded_by_employee_id
                    == employee_id
                )
            )


def authorization_headers(client: TestClient, email: str) -> dict[str, str]:
    """Return Bearer authorization headers for a synthetic employee."""

    from test_claim_access import login

    token = login(client, email)
    return {"Authorization": f"Bearer {token}"}


def install_fake_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install deterministic database-backed evidence persistence."""

    def fake_persist(
        db,
        file_path: str | Path,
        claim_id,
        uploader_employee_id,
        filename: str | None = None,
        embedding_service=None,
        **kwargs,
    ):
        document = ClaimEvidenceDocument(
            claim_id=claim_id,
            filename=filename or Path(file_path).name,
            checksum_sha256=uuid4().hex + uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=Path(file_path).stat().st_size,
            uploaded_by_employee_id=uploader_employee_id,
            storage_provider=kwargs.get("storage_provider"),
            storage_bucket=kwargs.get("storage_bucket"),
            storage_key=kwargs.get("storage_key"),
            storage_status=kwargs.get("storage_status"),
            status="processed",
        )

        document.chunks.append(
            ClaimEvidenceChunk(
                page_number=1,
                chunk_index=0,
                chunk_id=uuid4().hex,
                text="Synthetic claim evidence text for API testing.",
                extraction_method="native",
                embedding=None,
                embedding_model=None,
                embedded_at=None,
            )
        )

        db.add(document)
        db.flush()

        return document

    monkeypatch.setattr(
        evidence_routes,
        "persist_claim_evidence",
        fake_persist,
    )


def test_claim_evidence_upload_requires_authentication(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Unauthenticated users cannot upload claim evidence."""

    response = client.post(
        UPLOAD_URL.format(claim_id=claims_scenario["adjuster_claim_id"]),
        files={
            "file": (
                "evidence.pdf",
                b"%PDF-1.4 synthetic evidence",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 401


def test_claim_evidence_upload_rejects_inaccessible_claim(
    client: TestClient,
    claims_scenario: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An adjuster cannot upload evidence to another adjuster's claim."""

    def persistence_must_not_run(**kwargs):
        pytest.fail("Persistence must not run for an inaccessible claim.")

    monkeypatch.setattr(
        evidence_routes,
        "persist_claim_evidence",
        persistence_must_not_run,
    )

    headers = authorization_headers(
        client,
        claims_scenario["adjuster_email"],
    )

    response = client.post(
        UPLOAD_URL.format(claim_id=claims_scenario["other_claim_id"]),
        headers=headers,
        files={
            "file": (
                "evidence.pdf",
                b"%PDF-1.4 synthetic evidence",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Claim not found or access denied."
    )


def test_claim_evidence_upload_rejects_non_pdf(
    client: TestClient,
    upload_employee: dict,
) -> None:
    """Only PDF filenames are accepted."""

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "evidence.txt",
                b"Synthetic evidence text",
                "text/plain",
            )
        },
    )

    assert response.status_code == 415
    assert response.json()["detail"] == (
        "Only PDF documents are supported."
    )


def test_claim_evidence_upload_rejects_empty_pdf(
    client: TestClient,
    upload_employee: dict,
) -> None:
    """Empty PDF uploads are rejected."""

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "empty.pdf",
                b"",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "The uploaded PDF is empty."
    )


def test_claim_evidence_upload_rejects_oversized_pdf(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uploads exceeding the configured PDF limit are rejected."""

    monkeypatch.setattr(
        evidence_routes,
        "MAX_PDF_SIZE_BYTES",
        10,
    )

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "large.pdf",
                b"%PDF-1.4 " + (b"A" * 20),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "The PDF exceeds the 20 MiB size limit."
    )


def test_claim_evidence_upload_returns_conflict_for_duplicate(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate evidence is returned as HTTP 409."""

    def duplicate_evidence(**kwargs):
        raise DuplicateClaimEvidenceError(
            "This evidence document already exists for the claim."
        )

    monkeypatch.setattr(
        evidence_routes,
        "persist_claim_evidence",
        duplicate_evidence,
    )

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "duplicate.pdf",
                b"%PDF-1.4 synthetic evidence",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This evidence document already exists for the claim."
    )


def test_claim_evidence_upload_handles_processing_failure(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evidence processing failures return HTTP 422."""

    def fail_processing(**kwargs):
        raise EvidencePersistenceError(
            "Synthetic evidence processing failure."
        )

    monkeypatch.setattr(
        evidence_routes,
        "persist_claim_evidence",
        fail_processing,
    )

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "evidence.pdf",
                b"%PDF-1.4 synthetic evidence",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Synthetic evidence processing failure."
    )


def test_claim_evidence_upload_handles_embedding_service_failure(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedding service failures return HTTP 503."""

    def fail_embedding(**kwargs):
        raise EmbeddingServiceError(
            "Synthetic embedding service failure."
        )

    monkeypatch.setattr(
        evidence_routes,
        "persist_claim_evidence",
        fail_embedding,
    )

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "evidence.pdf",
                b"%PDF-1.4 synthetic evidence",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The evidence embedding service is temporarily unavailable."
    )


def test_claim_evidence_upload_persists_document_chunks_and_audit_event(
    client: TestClient,
    upload_employee: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful uploads persist evidence, chunks, and an audit event."""

    install_fake_persistence(monkeypatch)

    headers = authorization_headers(client, upload_employee["email"])

    response = client.post(
        UPLOAD_URL.format(claim_id=upload_employee["claim_id"]),
        headers=headers,
        files={
            "file": (
                "synthetic-evidence.pdf",
                b"%PDF-1.4 synthetic evidence content",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["claim_id"] == str(upload_employee["claim_id"])
    assert body["filename"] == "synthetic-evidence.pdf"
    assert body["status"] == "processed"
    assert body["chunk_count"] == 1
    assert body["document_id"]

    with SessionLocal() as session:
        document = session.get(
            ClaimEvidenceDocument,
            body["document_id"],
        )

        assert document is not None
        assert document.claim_id == upload_employee["claim_id"]
        assert document.uploaded_by_employee_id == upload_employee["id"]
        assert document.status == "processed"

        chunks = session.scalars(
            select(ClaimEvidenceChunk).where(
                ClaimEvidenceChunk.document_id == document.id
            )
        ).all()

        assert len(chunks) == 1
        assert chunks[0].page_number == 1
        assert chunks[0].text == (
            "Synthetic claim evidence text for API testing."
        )

        audit_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == str(document.id),
                AuditEvent.action == "claim_evidence_uploaded",
            )
        )

        assert audit_event is not None
        assert audit_event.actor_employee_id == upload_employee["id"]
        assert audit_event.resource_type == "claim_evidence_document"
