"""Database-backed tests for claim evidence semantic retrieval."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from claimsage.db.models import (
    Claim,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
    EmployeeRole,
)
from claimsage.db.session import SessionLocal
from claimsage.rag import evidence_retrieval_service
from claimsage.rag.evidence_retrieval_service import (
    EvidenceRetrievalError,
    get_document_evidence_chunks,
    search_claim_evidence,
)
from claimsage.services.claim_access import ClaimAccessDeniedError

TEST_MODEL = "test-evidence-retrieval-model"
TEST_VECTOR = [1.0] + [0.0] * 383
LOW_SIMILARITY_VECTOR = [0.0, 1.0] + [0.0] * 382


class FakeQueryEmbeddingService:
    """Deterministic embedding service for retrieval tests."""

    model_name = TEST_MODEL

    def embed_query(self, query: str) -> list[float]:
        return TEST_VECTOR


@pytest.fixture
def evidence_retrieval_scenario(monkeypatch):
    """Create isolated PostgreSQL data for evidence retrieval tests."""

    employee_id = uuid.uuid4()
    other_employee_id = uuid.uuid4()
    authorized_claim_id = uuid.uuid4()
    other_claim_id = uuid.uuid4()

    document_id = uuid.uuid4()
    other_claim_document_id = uuid.uuid4()
    unprocessed_document_id = uuid.uuid4()

    employee = Employee(
        id=employee_id,
        email=f"evidence-retrieval-{employee_id}@test.local",
        display_name="Evidence Retrieval Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"evidence-team-{employee_id}",
    )

    other_employee = Employee(
        id=other_employee_id,
        email=f"evidence-other-{other_employee_id}@test.local",
        display_name="Other Evidence Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"evidence-other-team-{other_employee_id}",
    )

    authorized_claim = Claim(
        id=authorized_claim_id,
        claim_number=f"EVR-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Evidence Claimant",
        claim_type="health",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
    )

    other_claim = Claim(
        id=other_claim_id,
        claim_number=f"EVR-{uuid.uuid4().hex[:12]}",
        claimant_name="Other Synthetic Claimant",
        claim_type="health",
        assigned_employee_id=other_employee_id,
        team_id=other_employee.team_id,
        status="under_review",
    )

    documents = [
        ClaimEvidenceDocument(
            id=document_id,
            claim_id=authorized_claim_id,
            filename="medical_report.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=employee_id,
            status="processed",
        ),
        ClaimEvidenceDocument(
            id=other_claim_document_id,
            claim_id=other_claim_id,
            filename="other_claim_report.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=other_employee_id,
            status="processed",
        ),
        ClaimEvidenceDocument(
            id=unprocessed_document_id,
            claim_id=authorized_claim_id,
            filename="processing_report.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=employee_id,
            status="processing",
        ),
    ]

    chunks = [
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=document_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Synthetic medical report describing the authorized claim.",
            extraction_method="native",
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=document_id,
            page_number=1,
            chunk_index=1,
            chunk_id=uuid.uuid4().hex,
            text="Second chunk from page one without an embedding.",
            extraction_method="native",
            embedding=None,
            embedding_model=None,
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=document_id,
            page_number=2,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Synthetic OCR evidence from page two.",
            extraction_method="ocr",
            ocr_confidence=96.5,
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=document_id,
            page_number=3,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Synthetic low similarity evidence.",
            extraction_method="native",
            embedding=LOW_SIMILARITY_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=document_id,
            page_number=4,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Evidence without an embedding must not be retrieved.",
            extraction_method="native",
            embedding=None,
            embedding_model=None,
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=other_claim_document_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Confidential evidence belonging to another claim.",
            extraction_method="native",
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        ClaimEvidenceChunk(
            id=uuid.uuid4(),
            document_id=unprocessed_document_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Evidence from an unprocessed document.",
            extraction_method="native",
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
    ]

    with SessionLocal.begin() as db:
        db.add_all([employee, other_employee])
        db.flush()

        db.add_all([authorized_claim, other_claim])
        db.flush()

        db.add_all(documents)
        db.flush()

        db.add_all(chunks)

    monkeypatch.setattr(
        evidence_retrieval_service,
        "get_embedding_service",
        lambda: FakeQueryEmbeddingService(),
    )

    scenario = {
        "employee_id": employee_id,
        "other_employee_id": other_employee_id,
        "authorized_claim_id": authorized_claim_id,
        "other_claim_id": other_claim_id,
        "document_id": document_id,
        "other_claim_document_id": other_claim_document_id,
        "unprocessed_document_id": unprocessed_document_id,
        "document_ids": {
            document_id,
            other_claim_document_id,
            unprocessed_document_id,
        },
    }

    yield scenario

    with SessionLocal.begin() as db:
        db.execute(
            delete(ClaimEvidenceChunk).where(
                ClaimEvidenceChunk.document_id.in_(
                    scenario["document_ids"]
                )
            )
        )
        db.execute(
            delete(ClaimEvidenceDocument).where(
                ClaimEvidenceDocument.id.in_(
                    scenario["document_ids"]
                )
            )
        )
        db.execute(
            delete(Claim).where(
                Claim.id.in_(
                    [
                        scenario["authorized_claim_id"],
                        scenario["other_claim_id"],
                    ]
                )
            )
        )
        db.execute(
            delete(Employee).where(
                Employee.id.in_(
                    [
                        scenario["employee_id"],
                        scenario["other_employee_id"],
                    ]
                )
            )
        )


def test_retrieval_returns_only_authorized_claim_evidence(
    evidence_retrieval_scenario,
):
    """Only evidence belonging to the authorized claim is returned."""

    with SessionLocal() as db:
        results = search_claim_evidence(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            query="medical report evidence",
            top_k=10,
        )

    assert len(results) == 3
    assert all(
        result.document_id == evidence_retrieval_scenario["document_id"]
        for result in results
    )
    assert all(
        "another claim" not in result.text
        for result in results
    )
    assert all(
        "unprocessed" not in result.text
        for result in results
    )


def test_retrieval_rejects_unauthorized_claim_before_embedding(
    evidence_retrieval_scenario,
    monkeypatch,
):
    """Unauthorized claims are rejected before embedding generation."""

    embedding_called = False

    def forbidden_embedding_service():
        nonlocal embedding_called
        embedding_called = True
        raise AssertionError(
            "Embedding generation must not run for unauthorized claims."
        )

    monkeypatch.setattr(
        evidence_retrieval_service,
        "get_embedding_service",
        forbidden_embedding_service,
    )

    with SessionLocal() as db:
        with pytest.raises(ClaimAccessDeniedError):
            search_claim_evidence(
                db,
                employee_id=evidence_retrieval_scenario["employee_id"],
                claim_id=evidence_retrieval_scenario["other_claim_id"],
                query="medical report evidence",
            )

    assert embedding_called is False


def test_document_retrieval_rejects_unauthorized_claim(
    evidence_retrieval_scenario,
):
    """Document reads require employee authorization for the claim."""
    with SessionLocal() as db:
        with pytest.raises(ClaimAccessDeniedError):
            get_document_evidence_chunks(
                db,
                employee_id=evidence_retrieval_scenario["employee_id"],
                claim_id=evidence_retrieval_scenario["other_claim_id"],
                document_id=evidence_retrieval_scenario["document_id"],
            )


def test_document_retrieval_is_scoped_to_claim_and_processed_status(
    evidence_retrieval_scenario,
):
    """Cross-claim and unprocessed documents do not return chunks."""
    with SessionLocal() as db:
        cross_claim_results = get_document_evidence_chunks(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            document_id=evidence_retrieval_scenario["other_claim_document_id"],
        )
        unprocessed_results = get_document_evidence_chunks(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            document_id=evidence_retrieval_scenario["unprocessed_document_id"],
        )
        missing_results = get_document_evidence_chunks(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            document_id=uuid.uuid4(),
        )

    assert cross_claim_results == []
    assert unprocessed_results == []
    assert missing_results == []


def test_document_retrieval_returns_all_chunks_in_source_order(
    evidence_retrieval_scenario,
):
    """Document reads include low-similarity and unembedded chunks in order."""
    with SessionLocal() as db:
        results = get_document_evidence_chunks(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            document_id=evidence_retrieval_scenario["document_id"],
        )

    assert len(results) == 5
    assert [
        (result.page_number, result.chunk_index)
        for result in results
    ] == [
        (1, 0),
        (1, 1),
        (2, 0),
        (3, 0),
        (4, 0),
    ]
    assert results[1].text == "Second chunk from page one without an embedding."
    assert results[1].similarity is None
    assert results[1].embedding_model is None


def test_document_retrieval_preserves_chunk_provenance(
    evidence_retrieval_scenario,
):
    """Each returned chunk retains identifiers and extraction provenance."""
    with SessionLocal() as db:
        results = get_document_evidence_chunks(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            document_id=evidence_retrieval_scenario["document_id"],
        )

    ocr_results = [
        result for result in results
        if result.extraction_method == "ocr"
    ]
    assert all(
        result.document_id == evidence_retrieval_scenario["document_id"]
        for result in results
    )
    assert all(result.filename == "medical_report.pdf" for result in results)
    assert all(result.chunk_id is not None for result in results)
    assert len({result.chunk_id for result in results}) == len(results)
    assert len(ocr_results) == 1
    assert ocr_results[0].page_number == 2
    assert ocr_results[0].chunk_index == 0
    assert ocr_results[0].similarity is None
    assert ocr_results[0].ocr_confidence == 96.5


@pytest.mark.parametrize(
    "invalid_field",
    ["employee_id", "claim_id", "document_id"],
)
def test_document_retrieval_rejects_non_uuid_inputs(
    evidence_retrieval_scenario,
    invalid_field,
):
    """All identity inputs must be UUIDs before authorization or query."""
    arguments = {
        "employee_id": evidence_retrieval_scenario["employee_id"],
        "claim_id": evidence_retrieval_scenario["authorized_claim_id"],
        "document_id": evidence_retrieval_scenario["document_id"],
    }
    arguments[invalid_field] = "not-a-uuid"

    with SessionLocal() as db:
        with pytest.raises(ValueError, match=f"{invalid_field} must be a UUID"):
            get_document_evidence_chunks(db, **arguments)


def test_retrieval_preserves_page_and_ocr_provenance(
    evidence_retrieval_scenario,
):
    """Retrieved evidence retains page and OCR extraction metadata."""

    with SessionLocal() as db:
        results = search_claim_evidence(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            query="medical report evidence",
            top_k=10,
        )

    ocr_results = [
        result for result in results
        if result.extraction_method == "ocr"
    ]

    assert len(ocr_results) == 1
    assert ocr_results[0].page_number == 2
    assert ocr_results[0].ocr_confidence == 96.5


def test_retrieval_excludes_chunks_below_similarity_threshold(
    evidence_retrieval_scenario,
):
    """Chunks below the configured similarity threshold are excluded."""

    with SessionLocal() as db:
        results = search_claim_evidence(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            query="medical report evidence",
            top_k=10,
            min_similarity=0.8,
        )

    assert len(results) == 2
    assert all(result.similarity >= 0.8 for result in results)
    assert all(
        "low similarity" not in result.text
        for result in results
    )


def test_retrieval_respects_top_k(evidence_retrieval_scenario):
    """The result count never exceeds top_k."""

    with SessionLocal() as db:
        results = search_claim_evidence(
            db,
            employee_id=evidence_retrieval_scenario["employee_id"],
            claim_id=evidence_retrieval_scenario["authorized_claim_id"],
            query="medical report evidence",
            top_k=1,
        )

    assert len(results) == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": ""}, "Search query must not be empty."),
        ({"top_k": 0}, "top_k must be between 1 and 20."),
        ({"top_k": 21}, "top_k must be between 1 and 20."),
        ({"top_k": True}, "top_k must be between 1 and 20."),
        (
            {"min_similarity": -0.1},
            "min_similarity must be between 0 and 1.",
        ),
        (
            {"min_similarity": 1.1},
            "min_similarity must be between 0 and 1.",
        ),
        (
            {"min_similarity": float("nan")},
            "min_similarity must be between 0 and 1.",
        ),
    ],
)
def test_retrieval_rejects_invalid_parameters(
    evidence_retrieval_scenario,
    kwargs,
    message,
):
    """Invalid search parameters are rejected before database retrieval."""

    arguments = {
        "employee_id": evidence_retrieval_scenario["employee_id"],
        "claim_id": evidence_retrieval_scenario["authorized_claim_id"],
        "query": "medical report evidence",
        **kwargs,
    }

    with SessionLocal() as db:
        with pytest.raises(ValueError, match=message):
            search_claim_evidence(db, **arguments)


def test_retrieval_rejects_invalid_query_embedding(
    evidence_retrieval_scenario,
    monkeypatch,
):
    """Unexpected query embedding dimensions fail safely."""

    class InvalidEmbeddingService:
        model_name = TEST_MODEL

        def embed_query(self, query: str) -> list[float]:
            return [1.0, 0.0]

    monkeypatch.setattr(
        evidence_retrieval_service,
        "get_embedding_service",
        lambda: InvalidEmbeddingService(),
    )

    with SessionLocal() as db:
        with pytest.raises(
            EvidenceRetrievalError,
            match="invalid vector shape or value",
        ):
            search_claim_evidence(
                db,
                employee_id=evidence_retrieval_scenario["employee_id"],
                claim_id=evidence_retrieval_scenario["authorized_claim_id"],
                query="medical report evidence",
            )
