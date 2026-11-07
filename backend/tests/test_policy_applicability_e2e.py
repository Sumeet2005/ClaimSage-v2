"""Isolated end-to-end regression for policy upload and retrieval."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from test_claim_access import login

from claimsage.agents import graph as graph_module
from claimsage.agents.graph import run_investigation
from claimsage.agents.schemas import (
    PolicyAnalystOutput,
    ReviewReportOutput,
    SupervisorPlan,
)
from claimsage.db.models import (
    Claim,
    Employee,
    PolicyChunk,
    PolicyClause,
    PolicyDocument,
)
from claimsage.db.session import SessionLocal
from claimsage.rag import retrieval_service
from claimsage.rag.document_loader import DocumentChunk, PageText
from claimsage.rag.embedding_service import EMBEDDING_DIMENSIONS
from claimsage.rag.retrieval_service import search_policy_chunks
from claimsage.services import (
    document_persistence,
    embedding_persistence,
    policy_embedding_ingestion,
)

UPLOAD_URL = "/api/v1/policies/documents"
POLICY_IDENTIFIER = "SYN-PROP-POL-001"
MOTOR_POLICY_IDENTIFIER = "IRDAN190RP0042V01100001"
TEST_MODEL = "test-policy-applicability-model"
TEST_VECTOR = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


@pytest.fixture(autouse=True)
def require_explicit_test_database() -> None:
    """Prevent this record-writing integration test from using a dev database."""

    bind = SessionLocal.kw["bind"]
    if (
        bind.dialect.name != "postgresql"
        or bind.url.database != "claimsage_test"
    ):
        pytest.fail(
            "Policy applicability integration requires PostgreSQL "
            "claimsage_test.",
            pytrace=False,
        )
    try:
        with SessionLocal() as session:
            database_name = session.scalar(text("SELECT current_database()"))
    except SQLAlchemyError:
        pytest.fail(
            "Could not verify the PostgreSQL test database; "
            "connection details suppressed.",
            pytrace=False,
        )
    if database_name != "claimsage_test":
        pytest.fail(
            "Refusing policy integration setup outside claimsage_test.",
            pytrace=False,
        )


class FakeEmbeddingService:
    """Deterministic local embeddings for the integration test."""

    model_name = TEST_MODEL

    def __init__(self) -> None:
        self.query_calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [TEST_VECTOR.copy() for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        self.query_calls += 1
        return TEST_VECTOR.copy()


def _authorization_headers(client: TestClient, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, email)}"}


def _install_synthetic_pdf_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise production persistence with deterministic synthetic PDF text."""

    def extract_pdf_pages(file_path: str | Path) -> list[PageText]:
        path = Path(file_path)
        content = path.read_bytes()
        source_name, text = content.decode().split("\n", maxsplit=1)
        return [
            PageText(
                source_name=source_name,
                document_sha256=hashlib.sha256(content).hexdigest(),
                page_number=1,
                text=text,
                extraction_method="native",
            )
        ]

    def chunk_pages(pages: list[PageText]) -> list[DocumentChunk]:
        return [
            DocumentChunk(
                chunk_id=uuid4().hex,
                source_name=page.source_name,
                document_sha256=page.document_sha256,
                page_number=page.page_number,
                chunk_index=0,
                text=page.text,
                extraction_method=page.extraction_method,
                ocr_confidence=page.ocr_confidence,
            )
            for page in pages
        ]

    monkeypatch.setattr(
        document_persistence,
        "extract_pdf_pages",
        extract_pdf_pages,
    )
    monkeypatch.setattr(document_persistence, "chunk_pages", chunk_pages)


def _upload_policy(
    client: TestClient,
    *,
    headers: dict[str, str],
    filename: str,
    passage: str,
    claim_type: str | None,
    policy_identifier: str | None,
    insurance_type: str | None = None,
    policy_version: str | None = None,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> UUID:
    form_data: dict[str, str | list[str]] = {}
    if claim_type is not None:
        form_data["supported_claim_types"] = [claim_type]
    if policy_identifier is not None:
        form_data["policy_identifier"] = policy_identifier
    if insurance_type is not None:
        form_data["insurance_type"] = insurance_type
    if policy_version is not None:
        form_data["policy_version"] = policy_version
    if effective_from is not None:
        form_data["effective_from"] = effective_from.isoformat()
    if effective_to is not None:
        form_data["effective_to"] = effective_to.isoformat()

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        data=form_data,
        files={
            "file": (
                filename,
                f"{filename}\n{passage}".encode(),
                "application/pdf",
            )
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == filename
    assert body["status"] == "ready"
    assert body["processing_error"] is None
    assert body["chunk_count"] == 1
    return UUID(body["document_id"])


def _grant_claim_access(
    client: TestClient,
    *,
    headers: dict[str, str],
    document_id: UUID,
    claim_id: UUID,
) -> UUID:
    response = client.post(
        f"{UPLOAD_URL}/{document_id}/access-grants",
        headers=headers,
        json={"claim_id": str(claim_id)},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def test_policy_upload_scoped_embedding_and_applicable_retrieval(
    client: TestClient,
    claims_scenario: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_synthetic_pdf_extraction(monkeypatch)
    embedding_service = FakeEmbeddingService()
    monkeypatch.setattr(
        policy_embedding_ingestion,
        "get_embedding_service",
        lambda: embedding_service,
    )
    monkeypatch.setattr(
        embedding_persistence,
        "get_embedding_service",
        lambda: embedding_service,
    )
    monkeypatch.setattr(
        retrieval_service,
        "get_embedding_service",
        lambda: embedding_service,
    )

    admin_headers = _authorization_headers(
        client,
        claims_scenario["admin_email"],
    )
    investigator_id: UUID
    claim_id = claims_scenario["adjuster_claim_id"]
    original_claim_metadata: tuple[str, str | None, date | None]
    with SessionLocal.begin() as session:
        claim = session.get(Claim, claim_id)
        investigator = session.scalar(
            select(Employee).where(
                Employee.email == claims_scenario["adjuster_email"]
            )
        )
        assert claim is not None
        assert investigator is not None
        investigator_id = investigator.id
        original_claim_metadata = (
            claim.claim_type,
            claim.policy_identifier,
            claim.loss_date,
        )
        claim.policy_identifier = POLICY_IDENTIFIER
        claim.loss_date = date(2026, 6, 1)

    document_ids: list[UUID] = []
    try:
        target_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_property_policy.pdf",
            passage="Synthetic property policy water-damage passage.",
            claim_type="property",
            policy_identifier=POLICY_IDENTIFIER,
            insurance_type="property",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        document_ids.append(target_id)
        health_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_health_policy.pdf",
            passage="Synthetic health policy hospital-bill passage.",
            claim_type="health",
            policy_identifier="SYN-HEALTH-POL-001",
            insurance_type="health",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        document_ids.append(health_id)
        other_policy_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_other_property_policy.pdf",
            passage="Synthetic property passage for a different policy.",
            claim_type="property",
            policy_identifier="SYN-PROP-POL-OTHER",
            insurance_type="property",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        document_ids.append(other_policy_id)
        unclassified_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_unclassified_policy.pdf",
            passage="Synthetic policy passage without applicability metadata.",
            claim_type=None,
            policy_identifier=None,
        )
        document_ids.append(unclassified_id)
        ungranted_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_ungranted_matching_policy.pdf",
            passage="Matching synthetic policy passage without an access grant.",
            claim_type="property",
            policy_identifier=POLICY_IDENTIFIER,
            insurance_type="property",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        document_ids.append(ungranted_id)
        incompatible_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_incompatible_embedding_policy.pdf",
            passage="Synthetic matching policy with an incompatible embedding.",
            claim_type="property",
            policy_identifier=POLICY_IDENTIFIER,
            insurance_type="property",
            policy_version="synthetic-v1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
        document_ids.append(incompatible_id)
        motor_id = _upload_policy(
            client,
            headers=admin_headers,
            filename="synthetic_motor_policy_missing_date.pdf",
            passage="Synthetic motor policy without verified applicability date.",
            claim_type="motor",
            policy_identifier=MOTOR_POLICY_IDENTIFIER,
        )
        document_ids.append(motor_id)

        with SessionLocal.begin() as session:
            unclassified = session.get(PolicyDocument, unclassified_id)
            assert unclassified is not None
            unclassified.policy_identifier = POLICY_IDENTIFIER
            unclassified.insurance_type = "property"
            unclassified.policy_version = "synthetic-v1"
            unclassified.effective_from = date(2026, 1, 1)
            unclassified.effective_to = date(2026, 12, 31)
            motor_document = session.get(PolicyDocument, motor_id)
            assert motor_document is not None
            motor_document.insurance_type = "auto"
            motor_document.policy_version = "synthetic-no-date"

        with SessionLocal() as session:
            target = session.get(PolicyDocument, target_id)
            assert target is not None
            assert target.status == "processed"
            assert target.policy_identifier == POLICY_IDENTIFIER
            assert target.insurance_type == "property"
            assert target.policy_version == "synthetic-v1"
            assert target.effective_from == date(2026, 1, 1)
            assert target.effective_to == date(2026, 12, 31)
            assert [
                entry.claim_type for entry in target.supported_claim_types
            ] == ["property"]
            clause = session.scalar(
                select(PolicyClause).where(
                    PolicyClause.document_id == target_id
                )
            )
            assert clause is not None
            assert clause.verification_status == "pending_review"
            assert clause.source_page_number == 1
            assert clause.clause_text == (
                "Synthetic property policy water-damage passage."
            )
            assert session.scalar(
                select(PolicyChunk.id).where(
                    PolicyChunk.document_id == target_id
                )
            ) is not None

            for document_id in document_ids:
                chunk = session.scalar(
                    select(PolicyChunk).where(
                        PolicyChunk.document_id == document_id
                    )
                )
                assert chunk is not None
                assert chunk.embedding is not None
                assert chunk.embedding_model == TEST_MODEL

        grants = {
            document_id: _grant_claim_access(
                client,
                headers=admin_headers,
                document_id=document_id,
                claim_id=claim_id,
            )
            for document_id in (
                target_id,
                health_id,
                other_policy_id,
                unclassified_id,
                incompatible_id,
                motor_id,
            )
        }

        with SessionLocal.begin() as session:
            incompatible_chunk = session.scalar(
                select(PolicyChunk).where(
                    PolicyChunk.document_id == incompatible_id
                )
            )
            assert incompatible_chunk is not None
            incompatible_chunk.embedding_model = "incompatible-model"

        with SessionLocal() as session:
            retrieved = search_policy_chunks(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
                query="synthetic property policy",
            )
        assert [chunk.document_id for chunk in retrieved] == [target_id]

        with SessionLocal.begin() as session:
            target_chunk = session.scalar(
                select(PolicyChunk).where(
                    PolicyChunk.document_id == target_id
                )
            )
            assert target_chunk is not None
            target_chunk.embedding_model = "incompatible-model"

        with SessionLocal() as session:
            assert search_policy_chunks(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
                query="synthetic property policy",
            ) == []

        with SessionLocal.begin() as session:
            target_chunk = session.scalar(
                select(PolicyChunk).where(
                    PolicyChunk.document_id == target_id
                )
            )
            assert target_chunk is not None
            target_chunk.embedding_model = TEST_MODEL

        monkeypatch.setattr(
            graph_module,
            "search_claim_evidence",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr(
            graph_module,
            "create_supervisor_plan",
            lambda **kwargs: SupervisorPlan(
                selected_analysts=["policy_analyst"],
                routing_rationale="Review applicable synthetic policy evidence.",
                human_review_required=True,
            ),
        )
        monkeypatch.setattr(
            graph_module,
            "analyze_policy",
            lambda **kwargs: PolicyAnalystOutput(
                summary="Synthetic policy analysis for human review.",
                overall_assessment="insufficient_evidence",
            ),
        )
        monkeypatch.setattr(
            graph_module,
            "analyze_review_report",
            lambda **kwargs: ReviewReportOutput(
                overall_status="insufficient_evidence",
                specialist_coverage=[],
                evidence_retrieval_status="completed",
                evidence_scope_note="Synthetic policy retrieval regression.",
                human_review_required=True,
            ),
        )

        with SessionLocal() as session:
            outcome = run_investigation(
                session=session,
                employee_id=investigator_id,
                claim_id=claim_id,
                task="Review policy wording relevant to the property claim.",
            )

        assert outcome["error"] is None
        assert outcome["policy_retrieval_status"] == "completed"
        assert outcome["result"] is not None
        assert outcome["result"]["human_review_required"] is True
        assert outcome["review_report"] is not None
        assert outcome["review_report_status"] == "completed"
        assert outcome["review_report"].human_review_required is True
        assert (
            outcome["result"]["review_report"]["human_review_required"]
            is True
        )
        evidence = outcome["policy_evidence"]
        assert len(evidence) == 1
        assert evidence[0]["document_id"] == str(target_id)
        assert evidence[0]["filename"] == "synthetic_property_policy.pdf"
        assert evidence[0]["page_number"] == 1
        assert evidence[0]["text"] == (
            "Synthetic property policy water-damage passage."
        )
        assert evidence[0]["clause_id"] == str(clause.id)
        assert evidence[0]["clause_identifier"] == clause.clause_identifier
        assert evidence[0]["policy_version"] == "synthetic-v1"
        assert evidence[0]["verification_status"] == "pending_review"
        assert all(
            evidence[0]["document_id"] != str(document_id)
            for document_id in (
                health_id,
                other_policy_id,
                unclassified_id,
                ungranted_id,
                incompatible_id,
            )
        )

        with SessionLocal.begin() as session:
            claim = session.get(Claim, claim_id)
            assert claim is not None
            claim.claim_type = "motor"
            claim.policy_identifier = MOTOR_POLICY_IDENTIFIER

        with SessionLocal() as session:
            motor_document = session.get(PolicyDocument, motor_id)
            assert motor_document is not None
            assert motor_document.policy_identifier == MOTOR_POLICY_IDENTIFIER
            assert motor_document.insurance_type == "auto"
            assert motor_document.policy_version == "synthetic-no-date"
            assert motor_document.effective_from is None
            motor_chunk = session.scalar(
                select(PolicyChunk).where(
                    PolicyChunk.document_id == motor_id
                )
            )
            assert motor_chunk is not None
            assert motor_chunk.embedding is not None
            query_calls_before_motor_lookup = embedding_service.query_calls
            assert not retrieval_service.has_applicable_policy_documents(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
            )
            assert search_policy_chunks(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
                query="synthetic motor policy",
            ) == []
        assert (
            embedding_service.query_calls
            == query_calls_before_motor_lookup
        )

        with SessionLocal.begin() as session:
            claim = session.get(Claim, claim_id)
            assert claim is not None
            (
                claim.claim_type,
                claim.policy_identifier,
                claim.loss_date,
            ) = original_claim_metadata

        embedding_calls_before_missing_identifier = embedding_service.query_calls
        with SessionLocal() as session:
            claim = session.get(Claim, claim_id)
            assert claim is not None
            claim.policy_identifier = None
            assert not retrieval_service.has_applicable_policy_documents(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
            )
            assert search_policy_chunks(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
                query="synthetic property policy",
            ) == []
        assert (
            embedding_service.query_calls
            == embedding_calls_before_missing_identifier
        )

        with SessionLocal.begin() as session:
            claim = session.get(Claim, claim_id)
            assert claim is not None
            claim.policy_identifier = POLICY_IDENTIFIER

        revoke_response = client.delete(
            f"{UPLOAD_URL}/{target_id}/access-grants/{grants[target_id]}",
            headers=admin_headers,
        )
        assert revoke_response.status_code == 204

        with SessionLocal() as session:
            assert search_policy_chunks(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
                query="synthetic property policy",
            ) == []
            assert not retrieval_service.has_applicable_policy_documents(
                session,
                employee_id=investigator_id,
                claim_id=claim_id,
            )

    finally:
        if document_ids:
            with SessionLocal.begin() as session:
                session.execute(
                    delete(PolicyDocument).where(
                        PolicyDocument.id.in_(document_ids)
                    )
                )
        with SessionLocal.begin() as session:
            claim = session.get(Claim, claim_id)
            if claim is not None:
                (
                    claim.claim_type,
                    claim.policy_identifier,
                    claim.loss_date,
                ) = original_claim_metadata
