"""Isolated tests for versioned policy applicability resolution."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, true
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from claimsage.db.models import (
    Claim,
    Employee,
    PolicyDocument,
    PolicyDocumentApplicability,
)
from claimsage.rag import retrieval_service
from claimsage.rag.embedding_service import EMBEDDING_DIMENSIONS
from claimsage.rag.retrieval_service import (
    RetrievedPolicyChunk,
    _applicable_policy_document_ids,
    _normalized_claim_type,
    search_policy_chunks,
)
from claimsage.schemas.policies import (
    PolicyDocumentApplicability as PolicyDocumentApplicabilitySchema,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_tables = [
        Employee.__table__,
        Claim.__table__,
        PolicyDocument.__table__,
        PolicyDocumentApplicability.__table__,
    ]
    PolicyDocumentApplicability.metadata.create_all(
        engine,
        tables=test_tables,
    )

    with Session(engine) as session:
        yield session

    PolicyDocumentApplicability.metadata.drop_all(
        engine,
        tables=test_tables,
    )
    engine.dispose()


def _create_claim(
    db: Session,
    *,
    policy_identifier: str | None = "SYN-PROP-POL-001",
    claim_type: str = "property",
    loss_date: date | None = date(2026, 6, 1),
) -> Claim:
    employee = Employee(
        email=f"{uuid4().hex}@example.test",
        display_name="Aarav Sharma",
    )
    db.add(employee)
    db.flush()
    claim = Claim(
        claim_number=f"CLM-{uuid4().hex[:12]}",
        claimant_name="Priya Patel",
        claim_type=claim_type,
        assigned_employee_id=employee.id,
        status="under_review",
        policy_identifier=policy_identifier,
        loss_date=loss_date,
    )
    db.add(claim)
    db.flush()
    return claim


def _create_policy(
    db: Session,
    *,
    policy_identifier: str = "SYN-PROP-POL-001",
    insurance_type: str = "property",
    policy_version: str | None = "v1",
    effective_from: date | None = date(2026, 1, 1),
    effective_to: date | None = date(2026, 12, 31),
    claim_type: str = "property",
) -> PolicyDocument:
    employee = db.scalar(select(Employee).limit(1))
    assert employee is not None
    document = PolicyDocument(
        filename=f"synthetic-policy-{uuid4().hex}.pdf",
        checksum_sha256=uuid4().hex * 2,
        mime_type="application/pdf",
        file_size_bytes=100,
        uploaded_by_employee_id=employee.id,
        status="processed",
        policy_identifier=policy_identifier,
        insurance_type=insurance_type,
        policy_version=policy_version,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.add(document)
    db.flush()
    db.add(
        PolicyDocumentApplicability(
            document_id=document.id,
            claim_type=claim_type,
        )
    )
    db.flush()
    return document


def _resolve(db: Session, claim: Claim) -> list[UUID]:
    return _applicable_policy_document_ids(
        db,
        claim=claim,
        normalized_type=_normalized_claim_type(claim.claim_type),
        document_access_filter=true(),
    )


def test_motor_alias_resolves_to_existing_auto_policy_taxonomy(
    db_session,
):
    claim = _create_claim(db_session, claim_type="motor")
    policy = _create_policy(
        db_session,
        insurance_type="auto",
        claim_type="auto",
    )

    assert _resolve(db_session, claim) == [policy.id]


def test_policy_applicability_normalizes_motor_alias():
    applicability = PolicyDocumentApplicabilitySchema.model_validate(
        {
            "supported_claim_types": ["motor"],
            "policy_identifier": "SYN-MOTOR-POL-001",
            "insurance_type": "motor",
            "policy_version": "synthetic-v1",
            "effective_from": date(2026, 1, 1),
        }
    )

    assert applicability.supported_claim_types == ["auto"]
    assert applicability.insurance_type == "auto"


def test_selects_policy_version_effective_on_claim_loss_date(db_session):
    claim = _create_claim(db_session)
    expired = _create_policy(
        db_session,
        policy_version="v0",
        effective_from=date(2025, 1, 1),
        effective_to=date(2025, 12, 31),
    )
    applicable = _create_policy(db_session, policy_version="v1")

    assert _resolve(db_session, claim) == [applicable.id]
    assert expired.id not in _resolve(db_session, claim)


@pytest.mark.parametrize(
    "claim_values, policy_values",
    [
        (
            {"policy_identifier": None},
            {},
        ),
        (
            {"loss_date": None},
            {},
        ),
        (
            {},
            {"policy_version": None},
        ),
        (
            {},
            {"effective_from": None},
        ),
        (
            {"claim_type": "health"},
            {},
        ),
        (
            {},
            {"insurance_type": "health"},
        ),
        (
            {},
            {"claim_type": "auto"},
        ),
        (
            {},
            {"policy_identifier": "SYN-PROP-POL-OTHER"},
        ),
    ],
)
def test_fails_closed_for_missing_or_mismatched_policy_identity(
    db_session,
    claim_values,
    policy_values,
):
    claim = _create_claim(db_session, **claim_values)
    _create_policy(db_session, **policy_values)

    assert _resolve(db_session, claim) == []


def test_overlapping_policy_versions_fail_closed(db_session):
    claim = _create_claim(db_session)
    _create_policy(
        db_session,
        policy_version="v1",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 8, 1),
    )
    _create_policy(
        db_session,
        policy_version="v2",
        effective_from=date(2026, 5, 1),
        effective_to=date(2026, 12, 31),
    )

    assert _resolve(db_session, claim) == []


def test_missing_claim_loss_date_fails_before_policy_query() -> None:
    session = MagicMock(spec=Session)
    claim = SimpleNamespace(
        policy_identifier="SYN-PROP-POL-001",
        loss_date=None,
    )

    assert (
        _applicable_policy_document_ids(
            session,
            claim=claim,
            normalized_type="property",
            document_access_filter=true(),
        )
        == []
    )
    session.execute.assert_not_called()


def test_policy_applicability_query_requires_known_effective_from() -> None:
    session = MagicMock(spec=Session)
    session.execute.return_value.all.return_value = []
    claim = SimpleNamespace(
        policy_identifier="SYN-PROP-POL-001",
        loss_date=date(2026, 6, 1),
    )

    assert (
        _applicable_policy_document_ids(
            session,
            claim=claim,
            normalized_type="property",
            document_access_filter=true(),
        )
        == []
    )
    statement = session.execute.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "policy_documents.effective_from IS NOT NULL" in compiled


@pytest.mark.parametrize(
    ("insurer_name", "product_name"),
    [
        (None, "New India Mediclaim Policy"),
        ("New India Assurance", None),
        (" ", "New India Mediclaim Policy"),
    ],
)
def test_health_applicability_fails_closed_without_insurer_or_product(
    insurer_name: str | None,
    product_name: str | None,
) -> None:
    session = MagicMock(spec=Session)
    claim = SimpleNamespace(
        policy_identifier="SYN-HEALTH-POL-001",
        loss_date=date(2022, 6, 1),
        insurer_name=insurer_name,
        product_name=product_name,
    )

    assert (
        _applicable_policy_document_ids(
            session,
            claim=claim,
            normalized_type="health",
            document_access_filter=true(),
        )
        == []
    )
    session.execute.assert_not_called()


def test_health_applicability_query_matches_insurer_and_product() -> None:
    session = MagicMock(spec=Session)
    session.execute.return_value.all.return_value = []
    claim = SimpleNamespace(
        policy_identifier="SYN-HEALTH-POL-001",
        loss_date=date(2022, 6, 1),
        insurer_name=" New India Assurance ",
        product_name=" New India Mediclaim Policy ",
    )

    _applicable_policy_document_ids(
        session,
        claim=claim,
        normalized_type="health",
        document_access_filter=true(),
    )

    compiled = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "lower(trim(policy_documents.insurer_name))" in compiled
    assert "lower(trim(policy_documents.product_name))" in compiled


def test_legacy_policy_chunk_has_nullable_clause_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_id = uuid4()
    employee_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    claim = SimpleNamespace(
        policy_identifier="SYN-PROP-POL-001",
        claim_type="property",
        loss_date=date(2026, 6, 1),
    )
    chunk = SimpleNamespace(
        id=chunk_id,
        document_id=document_id,
        page_number=2,
        chunk_index=0,
        text="Verbatim legacy policy passage.",
        embedding_model="synthetic-model",
    )
    session = MagicMock(spec=Session)
    session.execute.return_value.all.return_value = [
        (
            chunk,
            "legacy_policy.pdf",
            "https://policy.example.test/legacy.pdf",
            "Synthetic Assurance",
            "Synthetic Health Product",
            0.1,
            "v1",
            date(2026, 1, 1),
            date(2026, 12, 31),
            None,
            None,
            None,
            None,
            None,
        )
    ]

    class FakeEmbeddingService:
        model_name = "synthetic-model"

        @staticmethod
        def embed_query(_query: str) -> list[float]:
            return [0.0] * EMBEDDING_DIMENSIONS

    monkeypatch.setattr(
        retrieval_service,
        "get_authorized_claim",
        lambda *_args, **_kwargs: claim,
    )
    monkeypatch.setattr(
        retrieval_service,
        "build_policy_document_access_filter",
        lambda *_args, **_kwargs: true(),
    )
    monkeypatch.setattr(
        retrieval_service,
        "_applicable_policy_document_ids",
        lambda *_args, **_kwargs: [document_id],
    )
    monkeypatch.setattr(
        retrieval_service,
        "get_embedding_service",
        FakeEmbeddingService,
    )

    evidence = search_policy_chunks(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
        query="policy passage",
    )

    assert evidence == [
        RetrievedPolicyChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            filename="legacy_policy.pdf",
            page_number=2,
            chunk_index=0,
            text="Verbatim legacy policy passage.",
            similarity=0.9,
            embedding_model="synthetic-model",
            clause_id=None,
            clause_identifier=None,
            clause_category=None,
            verification_status=None,
            policy_version="v1",
            source_url="https://policy.example.test/legacy.pdf",
            insurer_name="Synthetic Assurance",
            product_name="Synthetic Health Product",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 12, 31),
        )
    ]
    statement = session.execute.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "LEFT OUTER JOIN policy_clauses" in compiled
