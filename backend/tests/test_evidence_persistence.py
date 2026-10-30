"""Tests for claim evidence persistence."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from claimsage.db.base import Base
from claimsage.db.models import (
    Claim,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
)
from claimsage.rag.document_loader import DocumentChunk, PageText
from claimsage.rag.embedding_service import EMBEDDING_DIMENSIONS
from claimsage.services import evidence_persistence as persistence


class FakeEmbeddingService:
    """Deterministic embedding service for tests."""

    model_name = "test-local-model"

    def __init__(self, vectors=None, error=None):
        self.vectors = vectors or []
        self.error = error
        self.received_batches = []

    def embed_texts(self, texts):
        self.received_batches.append(list(texts))

        if self.error:
            raise self.error

        start = sum(
            len(batch) for batch in self.received_batches[:-1]
        )
        return self.vectors[start : start + len(texts)]


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(
        dbapi_connection,
        _connection_record,
    ):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin_sqlite_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def claim_and_employee(db_session):
    employee = Employee(
        email=f"{uuid4().hex}@example.test",
        display_name="Synthetic Employee",
    )
    db_session.add(employee)
    db_session.flush()

    claim = Claim(
        claim_number=f"CLM-{uuid4().hex[:12]}",
        claimant_name="Synthetic Claimant",
        claim_type="motor",
        status="under_review",
        assigned_employee_id=employee.id,
        team_id="team-test",
        summary="Synthetic test claim",
    )
    db_session.add(claim)
    db_session.flush()

    return claim, employee


@pytest.fixture
def fake_pdf(tmp_path):
    path = tmp_path / "synthetic-evidence.pdf"
    path.write_bytes(b"%PDF-synthetic-evidence")
    return path


@pytest.fixture
def mock_extraction(monkeypatch):
    checksum = "a" * 64

    pages = [
        PageText(
            source_name="synthetic-evidence.pdf",
            document_sha256=checksum,
            page_number=1,
            text="Synthetic claim evidence on page one.",
            extraction_method="native",
        ),
        PageText(
            source_name="synthetic-evidence.pdf",
            document_sha256=checksum,
            page_number=2,
            text="Synthetic OCR evidence on page two.",
            extraction_method="ocr",
            ocr_confidence=94.5,
        ),
    ]

    chunks = [
        DocumentChunk(
            chunk_id="1" * 64,
            source_name="synthetic-evidence.pdf",
            document_sha256=checksum,
            page_number=1,
            chunk_index=0,
            text="Synthetic claim evidence on page one.",
            extraction_method="native",
        ),
        DocumentChunk(
            chunk_id="2" * 64,
            source_name="synthetic-evidence.pdf",
            document_sha256=checksum,
            page_number=2,
            chunk_index=0,
            text="Synthetic OCR evidence on page two.",
            extraction_method="ocr",
            ocr_confidence=94.5,
        ),
    ]

    monkeypatch.setattr(
        persistence,
        "extract_pdf_pages",
        lambda _: pages,
    )
    monkeypatch.setattr(
        persistence,
        "chunk_pages",
        lambda _: chunks,
    )

    return checksum


def make_embedding_service(count=2):
    return FakeEmbeddingService(
        vectors=[
            [0.1 * (index + 1)] * EMBEDDING_DIMENSIONS
            for index in range(count)
        ]
    )


def test_persists_evidence_document_chunks_and_embeddings(
    db_session,
    claim_and_employee,
    fake_pdf,
    mock_extraction,
):
    claim, employee = claim_and_employee
    service = make_embedding_service()

    document = persistence.persist_claim_evidence(
        db=db_session,
        file_path=fake_pdf,
        claim_id=claim.id,
        uploader_employee_id=employee.id,
        embedding_service=service,
    )

    assert document.status == "processed"
    assert document.claim_id == claim.id
    assert document.uploaded_by_employee_id == employee.id
    assert document.checksum_sha256 == mock_extraction
    assert document.filename == "synthetic-evidence.pdf"
    assert document.mime_type == "application/pdf"

    chunks = db_session.scalars(
        select(ClaimEvidenceChunk).where(
            ClaimEvidenceChunk.document_id == document.id
        )
    ).all()

    assert len(chunks) == 2
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.embedding is not None for chunk in chunks)
    assert all(
        chunk.embedding_model == "test-local-model"
        for chunk in chunks
    )
    assert all(chunk.embedded_at is not None for chunk in chunks)

    chunks_by_page = {
        chunk.page_number: chunk for chunk in chunks
    }

    assert chunks_by_page[1].extraction_method == "native"
    assert chunks_by_page[1].ocr_confidence is None

    assert chunks_by_page[2].extraction_method == "ocr"
    assert chunks_by_page[2].ocr_confidence == pytest.approx(94.5)


def test_rejects_duplicate_evidence_for_same_claim(
    db_session,
    claim_and_employee,
    fake_pdf,
    mock_extraction,
):
    claim, employee = claim_and_employee

    persistence.persist_claim_evidence(
        db_session,
        fake_pdf,
        claim.id,
        employee.id,
        embedding_service=make_embedding_service(),
    )

    with pytest.raises(persistence.DuplicateClaimEvidenceError):
        persistence.persist_claim_evidence(
            db_session,
            fake_pdf,
            claim.id,
            employee.id,
            embedding_service=make_embedding_service(),
        )


def test_allows_same_pdf_for_different_claims(
    db_session,
    claim_and_employee,
    fake_pdf,
    mock_extraction,
):
    first_claim, employee = claim_and_employee

    second_claim = Claim(
        claim_number=f"CLM-{uuid4().hex[:12]}",
        claimant_name="Another Synthetic Claimant",
        claim_type="motor",
        status="under_review",
        assigned_employee_id=employee.id,
        team_id="team-test",
    )
    db_session.add(second_claim)
    db_session.flush()

    first_document = persistence.persist_claim_evidence(
        db_session,
        fake_pdf,
        first_claim.id,
        employee.id,
        embedding_service=make_embedding_service(),
    )

    second_document = persistence.persist_claim_evidence(
        db_session,
        fake_pdf,
        second_claim.id,
        employee.id,
        embedding_service=make_embedding_service(),
    )

    assert first_document.id != second_document.id
    assert (
        first_document.checksum_sha256
        == second_document.checksum_sha256
    )


def test_rejects_missing_file(db_session, claim_and_employee):
    claim, employee = claim_and_employee

    with pytest.raises(persistence.EvidencePersistenceError):
        persistence.persist_claim_evidence(
            db_session,
            "missing-evidence.pdf",
            claim.id,
            employee.id,
            embedding_service=make_embedding_service(),
        )


def test_rejects_empty_file(
    db_session,
    claim_and_employee,
    tmp_path,
):
    claim, employee = claim_and_employee
    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")

    with pytest.raises(persistence.EvidencePersistenceError):
        persistence.persist_claim_evidence(
            db_session,
            empty_file,
            claim.id,
            employee.id,
            embedding_service=make_embedding_service(),
        )


def test_rejects_invalid_embedding_dimensions(
    db_session,
    claim_and_employee,
    fake_pdf,
    mock_extraction,
):
    claim, employee = claim_and_employee

    service = FakeEmbeddingService(
        vectors=[
            [0.1] * (EMBEDDING_DIMENSIONS - 1),
            [0.2] * EMBEDDING_DIMENSIONS,
        ]
    )

    with pytest.raises(
        persistence.EvidencePersistenceError,
        match="invalid vector",
    ):
        persistence.persist_claim_evidence(
            db_session,
            fake_pdf,
            claim.id,
            employee.id,
            embedding_service=service,
        )

    count = db_session.scalar(
        select(func.count()).select_from(ClaimEvidenceDocument)
    )
    assert count == 0


def test_embedding_failure_does_not_persist_document(
    db_session,
    claim_and_employee,
    fake_pdf,
    mock_extraction,
):
    claim, employee = claim_and_employee

    service = FakeEmbeddingService(
        error=RuntimeError("Synthetic embedding failure")
    )

    with pytest.raises(
        persistence.EvidencePersistenceError,
        match="Could not generate evidence embeddings",
    ):
        persistence.persist_claim_evidence(
            db_session,
            fake_pdf,
            claim.id,
            employee.id,
            embedding_service=service,
        )

    count = db_session.scalar(
        select(func.count()).select_from(ClaimEvidenceDocument)
    )
    assert count == 0


def test_rejects_invalid_filename(
    db_session,
    claim_and_employee,
    fake_pdf,
):
    claim, employee = claim_and_employee

    with pytest.raises(
        persistence.EvidencePersistenceError,
        match="filename",
    ):
        persistence.persist_claim_evidence(
            db_session,
            fake_pdf,
            claim.id,
            employee.id,
            filename="   ",
            embedding_service=make_embedding_service(),
        )


def test_caller_controls_transaction(
    db_session,
    claim_and_employee,
    fake_pdf,
    mock_extraction,
):
    claim, employee = claim_and_employee
    db_session.commit()

    service = make_embedding_service()

    document = persistence.persist_claim_evidence(
        db_session,
        fake_pdf,
        claim.id,
        employee.id,
        embedding_service=service,
    )

    document_id = document.id
    assert document.status == "processed"

    db_session.rollback()

    saved_document = db_session.scalar(
        select(ClaimEvidenceDocument).where(
            ClaimEvidenceDocument.id == document_id
        )
    )

    assert saved_document is None


def test_rejects_inconsistent_page_checksums(
    db_session,
    claim_and_employee,
    fake_pdf,
    monkeypatch,
):
    claim, employee = claim_and_employee

    pages = [
        PageText(
            source_name="evidence.pdf",
            document_sha256="a" * 64,
            page_number=1,
            text="First page",
        ),
        PageText(
            source_name="evidence.pdf",
            document_sha256="b" * 64,
            page_number=2,
            text="Second page",
        ),
    ]

    monkeypatch.setattr(
        persistence,
        "extract_pdf_pages",
        lambda _: pages,
    )

    with pytest.raises(
        persistence.EvidencePersistenceError,
        match="inconsistent document checksums",
    ):
        persistence.persist_claim_evidence(
            db_session,
            fake_pdf,
            claim.id,
            employee.id,
            embedding_service=make_embedding_service(),
        )
