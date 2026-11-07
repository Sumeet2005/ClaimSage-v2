from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from claimsage.db.base import Base
from claimsage.db.models import (
    Employee,
    PolicyChunk,
    PolicyClause,
    PolicyDocument,
    PolicyDocumentApplicability,
)
from claimsage.rag.document_loader import DocumentChunk, PageText
from claimsage.schemas.policies import PolicyDocumentApplicability as Applicability
from claimsage.services import document_persistence as persistence


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_tables = [
        Employee.__table__,
        PolicyDocument.__table__,
        PolicyDocumentApplicability.__table__,
        PolicyChunk.__table__,
        PolicyClause.__table__,
    ]

    Base.metadata.create_all(engine, tables=test_tables)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine, tables=test_tables)
    engine.dispose()


@pytest.fixture
def fake_pdf(tmp_path):
    pdf_path = tmp_path / "sample-policy.pdf"
    pdf_path.write_bytes(b"synthetic-pdf-content")
    return pdf_path


@pytest.fixture
def mock_extraction(monkeypatch):
    checksum = "a" * 64

    pages = [
        PageText(
            source_name="sample-policy.pdf",
            document_sha256=checksum,
            page_number=1,
            text="Synthetic native policy text on page one.",
            extraction_method="native",
            ocr_confidence=None,
        ),
        PageText(
            source_name="sample-policy.pdf",
            document_sha256=checksum,
            page_number=2,
            text="Synthetic OCR policy text on page two.",
            extraction_method="ocr",
            ocr_confidence=94.5,
        ),
    ]

    chunks = [
        DocumentChunk(
            chunk_id="chunk-one",
            source_name="sample-policy.pdf",
            document_sha256=checksum,
            page_number=1,
            chunk_index=0,
            text="Synthetic native policy text on page one.",
            extraction_method="native",
            ocr_confidence=None,
        ),
        DocumentChunk(
            chunk_id="chunk-two",
            source_name="sample-policy.pdf",
            document_sha256=checksum,
            page_number=2,
            chunk_index=0,
            text="Synthetic OCR policy text on page two.",
            extraction_method="ocr",
            ocr_confidence=94.5,
        ),
    ]

    monkeypatch.setattr(persistence, "extract_pdf_pages", lambda _: pages)
    monkeypatch.setattr(persistence, "chunk_pages", lambda _: chunks)

    return checksum


def test_persists_document_and_chunks(
    db_session,
    fake_pdf,
    mock_extraction,
):
    employee_id = uuid4()

    document = persistence.persist_policy_document(
        db=db_session,
        file_path=fake_pdf,
        uploader_employee_id=employee_id,
    )

    assert document.status == "processed"
    assert document.checksum_sha256 == mock_extraction
    assert document.filename == "sample-policy.pdf"
    assert document.mime_type == "application/pdf"
    assert document.file_size_bytes > 0

    saved_chunks = db_session.scalars(
        select(PolicyChunk).where(
            PolicyChunk.document_id == document.id
        )
    ).all()

    assert len(saved_chunks) == 2
    assert {chunk.page_number for chunk in saved_chunks} == {1, 2}
    assert {chunk.chunk_id for chunk in saved_chunks} == {
        "chunk-one",
        "chunk-two",
    }

    chunks_by_page = {
        chunk.page_number: chunk for chunk in saved_chunks
    }

    native_chunk = chunks_by_page[1]
    assert native_chunk.extraction_method == "native"
    assert native_chunk.ocr_confidence is None

    ocr_chunk = chunks_by_page[2]
    assert ocr_chunk.extraction_method == "ocr"
    assert ocr_chunk.ocr_confidence == pytest.approx(94.5)

    clauses = db_session.scalars(
        select(PolicyClause).where(
            PolicyClause.document_id == document.id
        )
    ).all()
    assert len(clauses) == len(saved_chunks)
    assert all(
        clause.verification_status == "pending_review"
        for clause in clauses
    )
    assert {
        clause.source_page_number for clause in clauses
    } == {1, 2}


def test_persists_verified_applicability_metadata(
    db_session,
    fake_pdf,
    mock_extraction,
):
    applicability = Applicability(
        supported_claim_types=[" Property ", "AUTO"],
        policy_identifier=" POLICY-2026-001 ",
        insurance_type="property",
        policy_version=" 2026-A ",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    document = persistence.persist_policy_document(
        db=db_session,
        file_path=fake_pdf,
        uploader_employee_id=uuid4(),
        applicability=applicability,
    )

    assert document.policy_identifier == "POLICY-2026-001"
    assert document.insurance_type == "property"
    assert document.policy_version == "2026-A"
    assert document.effective_from.isoformat() == "2026-01-01"
    assert document.effective_to.isoformat() == "2026-12-31"
    records = db_session.scalars(
        select(PolicyDocumentApplicability).where(
            PolicyDocumentApplicability.document_id == document.id
        )
    ).all()
    assert {record.claim_type for record in records} == {"property", "auto"}


@pytest.mark.parametrize(
    "values",
    [
        {
            "supported_claim_types": ["property"],
            "policy_identifier": "SYN-PROP-POL-001",
            "insurance_type": "property",
            "policy_version": "v1",
        },
        {
            "supported_claim_types": ["property"],
            "policy_identifier": "SYN-PROP-POL-001",
            "insurance_type": "auto",
            "policy_version": "v1",
            "effective_from": "2026-01-01",
        },
        {
            "supported_claim_types": ["travel"],
            "policy_identifier": "SYN-PROP-POL-001",
        },
        {
            "supported_claim_types": ["property"],
            "policy_identifier": "SYN-PROP-POL-001",
            "insurance_type": "property",
            "policy_version": "v1",
            "effective_from": "2026-12-31",
            "effective_to": "2026-01-01",
        },
    ],
)
def test_rejects_incomplete_or_invalid_policy_metadata(values):
    with pytest.raises(ValueError):
        Applicability.model_validate(values)


def test_normalizes_explicit_clause_heading_without_verifying_it():
    category, title, identifier = persistence._extract_clause_metadata(
        "Section 4.2 Coverage: Synthetic source wording.",
        page_number=3,
        chunk_index=1,
    )

    assert category == "coverage"
    assert title == "Synthetic source wording."
    assert identifier == "4.2"


def test_rejects_duplicate_document(
    db_session,
    fake_pdf,
    mock_extraction,
):
    employee_id = uuid4()

    persistence.persist_policy_document(
        db=db_session,
        file_path=fake_pdf,
        uploader_employee_id=employee_id,
    )

    with pytest.raises(persistence.DuplicatePolicyDocumentError):
        persistence.persist_policy_document(
            db=db_session,
            file_path=fake_pdf,
            uploader_employee_id=employee_id,
        )


def test_rejects_missing_file(db_session):
    with pytest.raises(persistence.DocumentPersistenceError):
        persistence.persist_policy_document(
            db=db_session,
            file_path="missing-policy.pdf",
            uploader_employee_id=uuid4(),
        )


def test_rejects_empty_file(db_session, tmp_path):
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")

    with pytest.raises(persistence.DocumentPersistenceError):
        persistence.persist_policy_document(
            db=db_session,
            file_path=empty_pdf,
            uploader_employee_id=uuid4(),
        )


def test_rolls_back_document_when_chunk_insert_fails(
    db_session,
    fake_pdf,
    mock_extraction,
    monkeypatch,
):
    original_chunk = persistence.PolicyChunk

    class FailingPolicyChunk:
        def __new__(cls, **kwargs):
            raise RuntimeError("Synthetic chunk insertion failure")

    monkeypatch.setattr(
        persistence,
        "PolicyChunk",
        FailingPolicyChunk,
    )

    with pytest.raises(RuntimeError, match="Synthetic chunk insertion failure"):
        persistence.persist_policy_document(
            db=db_session,
            file_path=fake_pdf,
            uploader_employee_id=uuid4(),
        )

    monkeypatch.setattr(persistence, "PolicyChunk", original_chunk)

    document_count = db_session.scalar(
        select(func.count()).select_from(PolicyDocument)
    )

    assert document_count == 0
