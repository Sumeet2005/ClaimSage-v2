"""Database-backed tests for authorization-aware policy retrieval."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete

from claimsage.db.models import (
    Claim,
    Employee,
    EmployeeRole,
    PolicyChunk,
    PolicyClause,
    PolicyDocument,
    PolicyDocumentAccess,
    PolicyDocumentApplicability,
)
from claimsage.db.session import SessionLocal
from claimsage.rag import retrieval_service
from claimsage.rag.retrieval_service import search_policy_chunks
from claimsage.services.claim_access import ClaimAccessDeniedError

TEST_MODEL = "test-retrieval-model"
TEST_POLICY_IDENTIFIER = "TEST-HEALTH-POLICY-001"
TEST_INSURER = "Synthetic Health Assurance"
TEST_PRODUCT = "Synthetic Health Product"
TEST_VECTOR = [1.0] + [0.0] * 383
LOW_SIMILARITY_VECTOR = [0.0, 1.0] + [0.0] * 382


class FakeQueryEmbeddingService:
    """Deterministic embedding service for retrieval tests."""

    model_name = TEST_MODEL

    def embed_query(self, query: str) -> list[float]:
        return TEST_VECTOR


@pytest.fixture
def retrieval_scenario(monkeypatch):
    """Create isolated PostgreSQL data for retrieval authorization tests."""

    employee_id = uuid.uuid4()
    other_employee_id = uuid.uuid4()
    adjuster_claim_id = uuid.uuid4()
    other_claim_id = uuid.uuid4()
    property_claim_id = uuid.uuid4()
    unlinked_claim_id = uuid.uuid4()
    mismatched_policy_claim_id = uuid.uuid4()
    mismatched_insurer_claim_id = uuid.uuid4()
    mismatched_product_claim_id = uuid.uuid4()

    team_document_id = uuid.uuid4()
    claim_document_id = uuid.uuid4()
    ungranted_document_id = uuid.uuid4()

    grant_ids = [uuid.uuid4(), uuid.uuid4()]
    chunk_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    employee = Employee(
        id=employee_id,
        email=f"retrieval-adjuster-{employee_id}@test.local",
        display_name="Retrieval Test Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"retrieval-team-{employee_id}",
    )

    other_employee = Employee(
        id=other_employee_id,
        email=f"retrieval-other-{other_employee_id}@test.local",
        display_name="Other Retrieval Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"other-team-{other_employee_id}",
    )

    adjuster_claim = Claim(
        id=adjuster_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Claimant One",
        claim_type="health",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
        policy_identifier=TEST_POLICY_IDENTIFIER,
        insurer_name=TEST_INSURER,
        product_name=TEST_PRODUCT,
        loss_date=date(2026, 6, 1),
    )

    other_claim = Claim(
        id=other_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Claimant Two",
        claim_type="health",
        assigned_employee_id=other_employee_id,
        team_id=other_employee.team_id,
        status="under_review",
        policy_identifier="OTHER-HEALTH-POLICY",
        insurer_name=TEST_INSURER,
        product_name=TEST_PRODUCT,
        loss_date=date(2026, 6, 1),
    )
    property_claim = Claim(
        id=property_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Property Claimant",
        claim_type="property",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
        policy_identifier=TEST_POLICY_IDENTIFIER,
        loss_date=date(2026, 6, 1),
    )
    unlinked_claim = Claim(
        id=unlinked_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Unlinked Claimant",
        claim_type="health",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
    )
    mismatched_policy_claim = Claim(
        id=mismatched_policy_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Policy Mismatch Claimant",
        claim_type="health",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
        policy_identifier="OTHER-HEALTH-POLICY",
        insurer_name=TEST_INSURER,
        product_name=TEST_PRODUCT,
    )
    mismatched_insurer_claim = Claim(
        id=mismatched_insurer_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Insurer Mismatch Claimant",
        claim_type="health",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
        policy_identifier=TEST_POLICY_IDENTIFIER,
        insurer_name="Other Synthetic Assurance",
        product_name=TEST_PRODUCT,
        loss_date=date(2026, 6, 1),
    )
    mismatched_product_claim = Claim(
        id=mismatched_product_claim_id,
        claim_number=f"RET-{uuid.uuid4().hex[:12]}",
        claimant_name="Synthetic Product Mismatch Claimant",
        claim_type="health",
        assigned_employee_id=employee_id,
        team_id=employee.team_id,
        status="under_review",
        policy_identifier=TEST_POLICY_IDENTIFIER,
        insurer_name=TEST_INSURER,
        product_name="Other Synthetic Health Product",
        loss_date=date(2026, 6, 1),
    )

    documents = [
        PolicyDocument(
            id=team_document_id,
            filename="retrieval_team_policy.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=employee_id,
            status="processed",
            policy_identifier=TEST_POLICY_IDENTIFIER,
            insurer_name=TEST_INSURER,
            product_name=TEST_PRODUCT,
            insurance_type="health",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        ),
        PolicyDocument(
            id=claim_document_id,
            filename="retrieval_claim_policy.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=employee_id,
            status="processed",
            policy_identifier=TEST_POLICY_IDENTIFIER,
            insurer_name=TEST_INSURER,
            product_name=TEST_PRODUCT,
            insurance_type="health",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        ),
        PolicyDocument(
            id=ungranted_document_id,
            filename="retrieval_ungranted_policy.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=employee_id,
            status="processed",
            policy_identifier=TEST_POLICY_IDENTIFIER,
            insurer_name=TEST_INSURER,
            product_name=TEST_PRODUCT,
            insurance_type="health",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        ),
    ]

    grants = [
        PolicyDocumentAccess(
            id=grant_ids[0],
            document_id=team_document_id,
            team_id=employee.team_id,
            claim_id=None,
            granted_by_employee_id=employee_id,
        ),
        PolicyDocumentAccess(
            id=grant_ids[1],
            document_id=claim_document_id,
            team_id=None,
            claim_id=adjuster_claim_id,
            granted_by_employee_id=employee_id,
        ),
    ]

    applicability = [
        PolicyDocumentApplicability(
            document_id=document_id,
            claim_type="health",
        )
        for document_id in (
            team_document_id,
            claim_document_id,
            ungranted_document_id,
        )
    ]

    chunks = [
        PolicyChunk(
            id=chunk_ids[0],
            document_id=team_document_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Synthetic team policy evidence for retrieval testing.",
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        PolicyChunk(
            id=chunk_ids[1],
            document_id=claim_document_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="Synthetic claim policy evidence for retrieval testing.",
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        PolicyChunk(
            id=chunk_ids[2],
            document_id=ungranted_document_id,
            page_number=1,
            chunk_index=0,
            chunk_id=uuid.uuid4().hex,
            text="This ungranted policy must never be returned.",
            embedding=TEST_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
        PolicyChunk(
            id=chunk_ids[3],
            document_id=team_document_id,
            page_number=1,
            chunk_index=1,
            chunk_id=uuid.uuid4().hex,
            text="Synthetic low-similarity policy evidence.",
            embedding=LOW_SIMILARITY_VECTOR,
            embedding_model=TEST_MODEL,
            embedded_at=datetime.now(UTC),
        ),
    ]

    with SessionLocal.begin() as db:
        db.add_all([employee, other_employee])
        db.flush()

        db.add_all(
            [
                adjuster_claim,
                other_claim,
                property_claim,
                unlinked_claim,
                mismatched_policy_claim,
                mismatched_insurer_claim,
                mismatched_product_claim,
            ]
        )
        db.flush()

        db.add_all(documents)
        db.flush()

        db.add_all(applicability)
        db.add_all(grants)
        db.add_all(chunks)
        db.flush()
        db.add_all(
            PolicyClause(
                document_id=chunk.document_id,
                source_chunk_id=chunk.id,
                clause_identifier=f"synthetic-{chunk.id}",
                clause_category="other",
                clause_text=chunk.text,
                source_page_number=chunk.page_number,
                verification_status="pending_review",
            )
            for chunk in chunks
        )

    monkeypatch.setattr(
        retrieval_service,
        "get_embedding_service",
        lambda: FakeQueryEmbeddingService(),
    )

    scenario = {
        "employee_id": employee_id,
        "other_employee_id": other_employee_id,
        "adjuster_claim_id": adjuster_claim_id,
        "other_claim_id": other_claim_id,
        "property_claim_id": property_claim_id,
        "unlinked_claim_id": unlinked_claim_id,
        "mismatched_policy_claim_id": mismatched_policy_claim_id,
        "mismatched_insurer_claim_id": mismatched_insurer_claim_id,
        "mismatched_product_claim_id": mismatched_product_claim_id,
        "team_document_id": team_document_id,
        "claim_document_id": claim_document_id,
        "ungranted_document_id": ungranted_document_id,
        "document_ids": {
            team_document_id,
            claim_document_id,
            ungranted_document_id,
        },
    }

    yield scenario

    with SessionLocal.begin() as db:
        db.execute(
            delete(PolicyChunk).where(
                PolicyChunk.document_id.in_(scenario["document_ids"])
            )
        )
        db.execute(
            delete(PolicyDocumentAccess).where(
                PolicyDocumentAccess.document_id.in_(
                    scenario["document_ids"]
                )
            )
        )
        db.execute(
            delete(PolicyDocument).where(
                PolicyDocument.id.in_(scenario["document_ids"])
            )
        )
        db.execute(
            delete(Claim).where(
                Claim.id.in_(
                    [
                        scenario["adjuster_claim_id"],
                        scenario["other_claim_id"],
                        scenario["property_claim_id"],
                        scenario["unlinked_claim_id"],
                        scenario["mismatched_policy_claim_id"],
                        scenario["mismatched_insurer_claim_id"],
                        scenario["mismatched_product_claim_id"],
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


def test_retrieval_returns_team_and_claim_granted_documents(
    retrieval_scenario,
):
    """Retrieval returns documents authorized by team and claim grants."""

    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["adjuster_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
        )

    returned_document_ids = {result.document_id for result in results}

    assert returned_document_ids == {
        retrieval_scenario["team_document_id"],
        retrieval_scenario["claim_document_id"],
    }


def test_retrieval_excludes_documents_without_access_grants(
    retrieval_scenario,
):
    """An ungranted document is excluded even when its vector matches."""

    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["adjuster_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
        )

    returned_document_ids = {result.document_id for result in results}

    assert retrieval_scenario["ungranted_document_id"] not in (
        returned_document_ids
    )


def test_retrieval_rejects_unauthorized_claim_before_embedding(
    retrieval_scenario,
    monkeypatch,
):
    """Unauthorized claims are rejected before embedding generation."""

    embedding_called = False

    def forbidden_embedding_service():
        nonlocal embedding_called
        embedding_called = True
        raise AssertionError(
            "Embedding generation must not run for an unauthorized claim."
        )

    monkeypatch.setattr(
        retrieval_service,
        "get_embedding_service",
        forbidden_embedding_service,
    )

    with SessionLocal() as db:
        with pytest.raises(ClaimAccessDeniedError):
            search_policy_chunks(
                db,
                employee_id=retrieval_scenario["employee_id"],
                claim_id=retrieval_scenario["other_claim_id"],
                query="synthetic policy evidence",
                top_k=10,
            )

    assert embedding_called is False


def test_retrieval_returns_only_chunks_from_authorized_documents(
    retrieval_scenario,
):
    """Returned chunk text must belong only to authorized documents."""

    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["adjuster_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
        )

    returned_text = [result.text for result in results]

    assert len(returned_text) == 3
    assert all(
        "must never be returned" not in text
        for text in returned_text
    )
    assert all(result.similarity >= 0.0 for result in results)


def test_retrieval_excludes_chunks_below_minimum_similarity(
    retrieval_scenario,
):
    """Chunks below min_similarity are excluded from retrieval results."""

    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["adjuster_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
            min_similarity=0.8,
        )

    assert len(results) == 2
    assert all(result.similarity >= 0.8 for result in results)

    returned_text = [result.text for result in results]

    assert "Synthetic low-similarity policy evidence." not in returned_text


def test_retrieval_excludes_health_policy_for_property_claim(
    retrieval_scenario,
):
    """Claim type and policy identifier must both match applicability."""

    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["property_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
        )

    assert results == []


def test_retrieval_requires_exact_claim_policy_identifier(
    retrieval_scenario,
):
    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["mismatched_policy_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
        )

    assert results == []


@pytest.mark.parametrize(
    "claim_key",
    ["mismatched_insurer_claim_id", "mismatched_product_claim_id"],
)
def test_health_retrieval_requires_matching_insurer_and_product(
    retrieval_scenario,
    claim_key,
):
    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario[claim_key],
            query="synthetic policy evidence",
            top_k=10,
        )

    assert results == []


def test_retrieval_excludes_documents_missing_applicability_metadata(
    retrieval_scenario,
):
    """Documents without explicit applicability metadata are never matches."""

    with SessionLocal.begin() as db:
        document = PolicyDocument(
            filename="unclassified_policy.pdf",
            checksum_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=retrieval_scenario["employee_id"],
            status="processed",
            policy_identifier=TEST_POLICY_IDENTIFIER,
        )
        db.add(document)
        db.flush()
        grant = PolicyDocumentAccess(
            document_id=document.id,
            team_id=f"retrieval-team-{retrieval_scenario['employee_id']}",
            claim_id=None,
            granted_by_employee_id=retrieval_scenario["employee_id"],
        )
        db.add(grant)
        db.flush()
        db.add(
            PolicyChunk(
                document_id=document.id,
                page_number=1,
                chunk_index=0,
                chunk_id=uuid.uuid4().hex,
                text="Unclassified policy text must not be retrieved.",
                embedding=TEST_VECTOR,
                embedding_model=TEST_MODEL,
            )
        )
        unclassified_id = document.id

    try:
        with SessionLocal() as db:
            results = search_policy_chunks(
                db,
                employee_id=retrieval_scenario["employee_id"],
                claim_id=retrieval_scenario["adjuster_claim_id"],
                query="synthetic policy evidence",
                top_k=10,
            )
        assert all(result.document_id != unclassified_id for result in results)
    finally:
        with SessionLocal.begin() as db:
            db.execute(
                delete(PolicyDocument).where(PolicyDocument.id == unclassified_id)
            )


def test_retrieval_requires_claim_policy_identifier(
    retrieval_scenario,
    monkeypatch,
):
    """Missing claim policy identity returns no documents without embedding."""

    embedding_called = False

    class TrackingEmbeddingService:
        model_name = TEST_MODEL

        def embed_query(self, query: str) -> list[float]:
            nonlocal embedding_called
            embedding_called = True
            return TEST_VECTOR

    monkeypatch.setattr(
        retrieval_service,
        "get_embedding_service",
        lambda: TrackingEmbeddingService(),
    )

    with SessionLocal() as db:
        results = search_policy_chunks(
            db,
            employee_id=retrieval_scenario["employee_id"],
            claim_id=retrieval_scenario["unlinked_claim_id"],
            query="synthetic policy evidence",
            top_k=10,
        )

    assert results == []
    assert embedding_called is False
