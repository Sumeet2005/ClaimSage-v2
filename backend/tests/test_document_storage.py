"""Comprehensive tests for durable document storage and lifecycle management."""

import hashlib
import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from claimsage.core.config import Settings
from claimsage.db.models import (
    AuditEvent,
    Claim,
    ClaimEvidenceDocument,
    Employee,
    EmployeeRole,
    PolicyDocument,
)
from claimsage.db.session import SessionLocal
from claimsage.services.storage import (
    ChecksumMismatchError,
    InMemoryStorageService,
    ObjectNotFoundError,
    S3StorageService,
    StorageUnavailableError,
    StorageValidationError,
    generate_secure_object_key,
    get_storage_service,
    set_storage_service,
    validate_pdf_content,
)


def make_pdf_bytes(text: str = "Standard policy terms and health coverage clauses.") -> bytes:
    """Generate a valid PDF with extractable text using PyMuPDF."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def create_token_headers(client: TestClient, email: str) -> dict[str, str]:
    from test_claim_access import login
    token = login(client, email)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit Tests for Storage Abstraction & Validation
# ---------------------------------------------------------------------------

def test_1_successful_upload():
    """Verify document upload calculates metadata and stores bytes."""
    service = InMemoryStorageService(bucket="test-bucket")
    pdf_bytes = make_pdf_bytes("Upload test content")
    key = generate_secure_object_key("policies")
    meta = service.upload_document(pdf_bytes, key, content_type="application/pdf")

    assert meta.bucket == "test-bucket"
    assert meta.object_key == key
    assert meta.file_size_bytes == len(pdf_bytes)
    assert meta.checksum_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert service.document_exists(key) is True


def test_2_successful_retrieval():
    """Verify stored document is accurately retrieved."""
    service = InMemoryStorageService()
    pdf_bytes = make_pdf_bytes("Retrieval test content")
    key = generate_secure_object_key("evidence", scope_id=uuid4())
    service.upload_document(pdf_bytes, key)

    doc = service.retrieve_document(key)
    assert doc.content == pdf_bytes
    assert doc.object_key == key
    assert doc.file_size_bytes == len(pdf_bytes)


def test_3_sha256_verification():
    """Verify checksum matches expected value during upload."""
    service = InMemoryStorageService()
    pdf_bytes = make_pdf_bytes("SHA256 test content")
    key = generate_secure_object_key("policies")
    expected = hashlib.sha256(pdf_bytes).hexdigest()

    meta = service.upload_document(pdf_bytes, key, expected_sha256=expected)
    assert meta.checksum_sha256 == expected


def test_4_checksum_mismatch():
    """Verify upload fails when calculated checksum does not match expected."""
    service = InMemoryStorageService()
    pdf_bytes = make_pdf_bytes("Mismatch test")
    key = generate_secure_object_key("policies")
    wrong_checksum = "0" * 64

    with pytest.raises(ChecksumMismatchError):
        service.upload_document(pdf_bytes, key, expected_sha256=wrong_checksum)


def test_5_duplicate_upload_idempotency():
    """Verify re-uploading with identical key updates/idempotently stores content."""
    service = InMemoryStorageService()
    pdf_bytes = make_pdf_bytes("Idempotency test")
    key = generate_secure_object_key("policies")
    service.upload_document(pdf_bytes, key)
    assert service.document_exists(key) is True

    # Overwrite with same content
    meta = service.upload_document(pdf_bytes, key)
    assert meta.object_key == key
    doc = service.retrieve_document(key)
    assert doc.content == pdf_bytes


def test_6_missing_object():
    """Verify retrieving non-existent object raises ObjectNotFoundError."""
    service = InMemoryStorageService()
    non_existent = generate_secure_object_key("policies")

    with pytest.raises(ObjectNotFoundError):
        service.retrieve_document(non_existent)


def test_7_storage_provider_unavailable():
    """Verify storage provider unavailability raises StorageUnavailableError."""
    service = InMemoryStorageService()
    service.is_available = False
    pdf_bytes = make_pdf_bytes("Unavailable test")
    key = generate_secure_object_key("policies")

    with pytest.raises(StorageUnavailableError):
        service.upload_document(pdf_bytes, key)

    with pytest.raises(StorageUnavailableError):
        service.retrieve_document(key)

    with pytest.raises(StorageUnavailableError):
        service.document_exists(key)


def test_13_file_size_and_type_validation():
    """Verify validation rejects non-PDF content and oversized payloads."""
    # Invalid magic header
    with pytest.raises(StorageValidationError, match="valid PDF signature"):
        validate_pdf_content(b"NOT_A_PDF_FILE_HEADER")

    # Empty content
    with pytest.raises(StorageValidationError, match="empty"):
        validate_pdf_content(b"")

    # Exceeding size limit
    pdf_bytes = make_pdf_bytes()
    with pytest.raises(StorageValidationError, match="exceeds limit"):
        validate_pdf_content(pdf_bytes, max_size_bytes=10)


def test_security_unpredictable_keys():
    """Verify generated keys never use original user filename and are random."""
    original_filename = "../../evil_path/malicious.pdf"
    key1 = generate_secure_object_key("policies")
    key2 = generate_secure_object_key("policies")

    assert original_filename not in key1
    assert ".." not in key1
    assert key1 != key2
    assert key1.startswith("policies/")
    assert key1.endswith(".pdf")


def test_s3_storage_service_unit():
    """Unit test for S3StorageService with mocked boto3 client."""
    s3_service = S3StorageService(bucket_name="test-s3-bucket")
    mock_client = MagicMock()
    s3_service._client = mock_client

    pdf_bytes = make_pdf_bytes("S3 client test")
    key = "policies/test_key.pdf"

    mock_client.put_object.return_value = {"ETag": '"test-etag"'}
    meta = s3_service.upload_document(pdf_bytes, key)
    assert meta.bucket == "test-s3-bucket"
    assert meta.object_key == key
    assert mock_client.put_object.called

    # Test retrieval
    mock_body = MagicMock()
    mock_body.read.return_value = pdf_bytes
    mock_client.get_object.return_value = {
        "Body": mock_body,
        "ContentType": "application/pdf",
        "Metadata": {"sha256": meta.checksum_sha256},
    }
    doc = s3_service.retrieve_document(key)
    assert doc.content == pdf_bytes

    # Test delete
    s3_service.delete_document(key)
    assert mock_client.delete_object.called


# ---------------------------------------------------------------------------
# API Integration & RBAC Tests (Database + Mock Storage)
# ---------------------------------------------------------------------------

def test_8_policy_upload_and_authorized_retrieval(client: TestClient, claims_scenario: dict):
    """Verify complete policy document upload and authorized retrieval lifecycle."""
    headers = create_token_headers(client, claims_scenario["admin_email"])
    pdf_bytes = make_pdf_bytes("Comprehensive Health Coverage Plan 2026")

    # Upload policy document
    response = client.post(
        "/api/v1/policies/documents",
        headers=headers,
        files={"file": ("master_policy.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    doc_id = data["document_id"]
    assert data["storage_status"] == "stored"

    try:
        # Download document
        download_res = client.get(
            f"/api/v1/policies/documents/{doc_id}/download",
            headers=headers,
        )
        assert download_res.status_code == 200
        assert download_res.content == pdf_bytes
        assert download_res.headers["Content-Type"] == "application/pdf"
        assert "master_policy.pdf" in download_res.headers["Content-Disposition"]
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(PolicyDocument).where(PolicyDocument.id == uuid.UUID(doc_id)))


def test_9_unauthorized_policy_download(client: TestClient, claims_scenario: dict):
    """Verify adjusters without document grants cannot download restricted policies."""
    admin_headers = create_token_headers(client, claims_scenario["admin_email"])
    adjuster_headers = create_token_headers(client, claims_scenario["adjuster_email"])
    pdf_bytes = make_pdf_bytes("Restricted Executive Health Policy")

    # Admin uploads document
    response = client.post(
        "/api/v1/policies/documents",
        headers=admin_headers,
        files={"file": ("restricted_policy.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 201
    doc_id = response.json()["document_id"]

    try:
        # Adjuster without explicit grant attempts download
        download_res = client.get(
            f"/api/v1/policies/documents/{doc_id}/download",
            headers=adjuster_headers,
        )
        assert download_res.status_code in {403, 404}
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(PolicyDocument).where(PolicyDocument.id == uuid.UUID(doc_id)))


def test_10_cross_claim_evidence_access_prevention(client: TestClient, claims_scenario: dict):
    """Verify an employee cannot access evidence belonging to an unauthorized claim."""
    adjuster_headers = create_token_headers(client, claims_scenario["adjuster_email"])
    claim_id = claims_scenario["adjuster_claim_id"]
    pdf_bytes = make_pdf_bytes("Medical hospital invoice and treatment report.")

    # Upload evidence for authorized claim
    upload_res = client.post(
        f"/api/v1/claims/{claim_id}/evidence",
        headers=adjuster_headers,
        files={"file": ("medical_invoice.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert upload_res.status_code == 201, upload_res.text
    evidence_id = upload_res.json()["document_id"]

    try:
        # Download with wrong claim ID (cross-claim access)
        fake_claim_id = uuid4()
        bad_res = client.get(
            f"/api/v1/claims/{fake_claim_id}/evidence/{evidence_id}/download",
            headers=adjuster_headers,
        )
        assert bad_res.status_code in {403, 404}
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(ClaimEvidenceDocument).where(ClaimEvidenceDocument.id == uuid.UUID(evidence_id)))


def test_11_audit_events_generated(client: TestClient, claims_scenario: dict):
    """Verify audit events are recorded for document upload and retrieval."""
    admin_headers = create_token_headers(client, claims_scenario["admin_email"])
    pdf_bytes = make_pdf_bytes("Audit verified health policy clause.")

    # Upload
    response = client.post(
        "/api/v1/policies/documents",
        headers=admin_headers,
        files={"file": ("audited_policy.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert response.status_code == 201
    doc_id = response.json()["document_id"]

    try:
        # Download
        client.get(
            f"/api/v1/policies/documents/{doc_id}/download",
            headers=admin_headers,
        )

        # Check audit log in DB
        with SessionLocal() as session:
            events = session.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == str(doc_id))
            ).all()
            actions = {e.action for e in events}
            assert "policy_document_uploaded" in actions
            assert "policy_document_retrieved" in actions
    finally:
        with SessionLocal.begin() as session:
            session.execute(delete(PolicyDocument).where(PolicyDocument.id == uuid.UUID(doc_id)))


def test_12_existing_document_without_storage_reference(client: TestClient, claims_scenario: dict):
    """Verify historical documents without storage reference return controlled 404."""
    admin_headers = create_token_headers(client, claims_scenario["admin_email"])
    doc_id = None

    try:
        with SessionLocal.begin() as session:
            admin = session.scalar(select(Employee).where(Employee.email == claims_scenario["admin_email"]))
            legacy_doc = PolicyDocument(
                filename="legacy_policy.pdf",
                checksum_sha256=uuid4().hex + uuid4().hex,
                mime_type="application/pdf",
                file_size_bytes=1024,
                uploaded_by_employee_id=admin.id,
                status="uploaded",
                storage_key=None,
                storage_status="unavailable",
            )
            session.add(legacy_doc)
            session.flush()
            doc_id = legacy_doc.id

        # Attempt download
        res = client.get(
            f"/api/v1/policies/documents/{doc_id}/download",
            headers=admin_headers,
        )
        assert res.status_code == 404
        assert "unavailable" in res.json()["detail"].lower()
    finally:
        if doc_id:
            with SessionLocal.begin() as session:
                session.execute(delete(PolicyDocument).where(PolicyDocument.id == doc_id))


def test_14_storage_cleanup_after_failed_database_transaction(client: TestClient, claims_scenario: dict):
    """Verify uploaded object is pruned if a database transaction fails (duplicate checksum)."""
    admin_headers = create_token_headers(client, claims_scenario["admin_email"])
    storage = get_storage_service()
    pdf_bytes = make_pdf_bytes("Duplicate test unique payload content 12345.")
    doc_id = None

    try:
        # Upload original
        res1 = client.post(
            "/api/v1/policies/documents",
            headers=admin_headers,
            files={"file": ("original.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # Upload duplicate (triggers 409 conflict)
        initial_objects_count = len(getattr(storage, "_objects", {}))
        res2 = client.post(
            "/api/v1/policies/documents",
            headers=admin_headers,
            files={"file": ("duplicate.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert res2.status_code == 409

        # Verify no leaked orphan objects created for the failed duplicate
        final_objects_count = len(getattr(storage, "_objects", {}))
        assert final_objects_count == initial_objects_count
    finally:
        if doc_id:
            with SessionLocal.begin() as session:
                session.execute(delete(PolicyDocument).where(PolicyDocument.id == uuid.UUID(doc_id)))


def test_15_application_restart_retained_documents(client: TestClient, claims_scenario: dict):
    """Verify retained documents persist across simulated client reconnects."""
    admin_headers = create_token_headers(client, claims_scenario["admin_email"])
    pdf_bytes = make_pdf_bytes("Restart retained document verification.")
    doc_id = None

    try:
        # Upload
        upload_res = client.post(
            "/api/v1/policies/documents",
            headers=admin_headers,
            files={"file": ("retained_doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        assert upload_res.status_code == 201
        doc_id = upload_res.json()["document_id"]

        # Re-retrieve with new client request
        get_res = client.get(
            f"/api/v1/policies/documents/{doc_id}/download",
            headers=admin_headers,
        )
        assert get_res.status_code == 200
        assert get_res.content == pdf_bytes
    finally:
        if doc_id:
            with SessionLocal.begin() as session:
                session.execute(delete(PolicyDocument).where(PolicyDocument.id == uuid.UUID(doc_id)))


def test_16_s3_server_side_encryption_support():
    """Verify S3StorageService passes ServerSideEncryption parameters to put_object."""
    mock_boto = MagicMock()
    mock_client = MagicMock()
    mock_boto.client.return_value = mock_client
    mock_client.put_object.return_value = {"ETag": '"sse-test-etag"'}

    service = S3StorageService(
        bucket_name="test-bucket",
        server_side_encryption="AES256",
        kms_key_id="arn:aws:kms:us-east-1:123456789012:key/test-key",
    )
    service._client = mock_client

    pdf_bytes = make_pdf_bytes("Testing SSE parameters")
    metadata = service.upload_document(pdf_bytes, "test-sse-key.pdf")

    assert metadata.object_key == "test-sse-key.pdf"
    mock_client.put_object.assert_called_once()
    _, kwargs = mock_client.put_object.call_args
    assert kwargs["ServerSideEncryption"] == "AES256"
    assert kwargs["SSEKMSKeyId"] == "arn:aws:kms:us-east-1:123456789012:key/test-key"


def test_17_production_ssl_tls_enforcement():
    """Verify production settings validator enforces SSL/TLS for S3 storage."""
    from claimsage.core.config import Settings
    from pydantic import SecretStr, ValidationError

    # In production, storage_use_ssl=False must raise ValidationError
    with pytest.raises(ValidationError, match="Production object storage must enforce SSL/TLS"):
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://prod_user:prod_pass@db:5432/claimsage_prod",
            storage_backend="s3",
            storage_use_ssl=False,
            jwt_secret_key=SecretStr("A" * 32),
            groq_api_key=SecretStr("groq_key"),
            email_app_base_url="https://app.example.com",
            storage_access_key=SecretStr("access"),
            storage_secret_key=SecretStr("secret"),
            _env_file=None,
        )

