"""Database-free checks for investigation serialization and domain handling."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from claimsage.db.models import (
    Claim,
    ClaimEvidenceChunk,
    ClaimEvidenceDocument,
    Employee,
    EmployeeRole,
    InvestigationFindingReference,
    InvestigationRun,
    PolicyChunk,
    PolicyClause,
    PolicyDocument,
)
from claimsage.schemas.investigation import InvestigationReviewRequest
from claimsage.services import investigation_persistence
from claimsage.services.investigation_persistence import (
    _add_relational_references,
    _make_finding,
    _retrieved_sources,
    _serialize_state,
    create_investigation_run,
    finish_investigation,
    is_investigation_complete,
    normalize_claim_domain,
    persist_progress,
)


def test_motor_and_health_domains_share_stable_values() -> None:
    assert normalize_claim_domain("auto") == "auto"
    assert normalize_claim_domain("motor") == "auto"
    assert normalize_claim_domain("health") == "health"
    assert normalize_claim_domain("property") == "other"


def test_state_snapshot_omits_trusted_employee_identity() -> None:
    employee_id = uuid4()
    claim_id = uuid4()

    snapshot = _serialize_state(
        {
            "employee_id": str(employee_id),
            "claim_id": str(claim_id),
            "result": {"human_review_required": True},
        }
    )

    assert "employee_id" not in snapshot
    assert snapshot["claim_id"] == str(claim_id)


def test_progress_and_terminal_state_persist_partial_ai_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock()
    investigation = SimpleNamespace(
        id=uuid4(),
        initiated_by_employee_id=uuid4(),
        current_stage=None,
        state_snapshot={},
        status="running",
        failure_type=None,
        completed_at=None,
    )
    monkeypatch.setattr(
        investigation_persistence,
        "_replace_findings",
        MagicMock(),
    )
    monkeypatch.setattr(
        investigation_persistence,
        "_sync_report",
        MagicMock(),
    )
    state = {
        "employee_id": str(uuid4()),
        "claim_id": str(uuid4()),
        "result": {
            "human_review_required": True,
            "provider_failures": [
                {
                    "stage": "policy_analysis",
                    "category": "rate_limited",
                    "status_code": 429,
                }
            ],
        },
        "review_report_status": "unavailable",
    }

    persist_progress(
        session,
        investigation=investigation,
        stage="policy_analyst",
        state=state,
    )
    finish_investigation(
        session,
        investigation=investigation,
        state=state,
    )

    assert investigation.current_stage is None
    assert investigation.status == "incomplete"
    assert investigation.state_snapshot["result"]["human_review_required"] is True
    assert investigation.state_snapshot["result"]["provider_failures"] == [
        {
            "stage": "policy_analysis",
            "category": "rate_limited",
            "status_code": 429,
        }
    ]
    assert "employee_id" not in investigation.state_snapshot
    assert session.commit.call_count == 2


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            {
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "insufficient_evidence",
                    "specialist_coverage": [],
                },
            },
            True,
        ),
        (
            {
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "completed",
                    "specialist_coverage": [
                        {"status": "unavailable"}
                    ],
                },
            },
            False,
        ),
        (
            {
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "completed",
                    "specialist_coverage": [],
                },
                "provider_failures": [{"stage": "policy_analyst"}],
            },
            False,
        ),
        (
            {
                "review_report_status": "unavailable",
                "review_report": None,
            },
            False,
        ),
    ],
)
def test_terminal_execution_status_reflects_required_agent_failures(
    result: dict[str, object],
    expected: bool,
) -> None:
    assert is_investigation_complete({"result": result}) is expected


def test_finding_keeps_exact_source_reference_and_resolution_status() -> None:
    evidence_id = "claim-chunk-123"

    finding = _make_finding(
        investigation_id=uuid4(),
        specialist="evidence",
        finding_type="factual_findings[0]",
        data={
            "finding": "A source-backed synthetic finding.",
            "supporting_evidence_ids": [evidence_id],
            "confidence": "medium",
        },
        retrieved={
            evidence_id: {
                "chunk_id": evidence_id,
                "document_id": "doc-1",
                "page_number": 2,
                "source_kind": "claim_evidence",
            }
        },
    )

    assert finding.evidence_references[0]["source_id"] == evidence_id
    assert finding.evidence_references[0]["resolved_from_retrieval"] is True
    assert finding.confidence == "medium"


@pytest.mark.parametrize(
    "decision",
    ["approve", "deny", "reject", "settle", "pay"],
)
def test_review_request_rejects_claim_disposition_decisions(
    decision: str,
) -> None:
    with pytest.raises(ValidationError):
        InvestigationReviewRequest.model_validate({"decision": decision})


def test_relational_references_resolve_uuid_and_sha256_chunk_ids() -> None:
    """Verify _add_relational_references resolves UUID primary keys (used by RAG retrieval),
    SHA-256 chunk_ids, and PolicyClause UUIDs while preserving provenance and marking
    unknown identifiers as unresolved without fabricating references.
    """
    claim_chunk_uuid = uuid4()
    claim_chunk_sha = "a" * 64
    policy_chunk_uuid = uuid4()
    policy_chunk_sha = "b" * 64
    clause_uuid = uuid4()
    unknown_id = str(uuid4())

    claim_chunk_obj = ClaimEvidenceChunk(
        id=claim_chunk_uuid,
        chunk_id=claim_chunk_sha,
    )
    policy_chunk_obj = PolicyChunk(
        id=policy_chunk_uuid,
        chunk_id=policy_chunk_sha,
    )
    clause_obj = PolicyClause(
        id=clause_uuid,
        clause_identifier="clause-1",
    )

    state = {
        "claim_evidence": [
            {
                "chunk_id": str(claim_chunk_uuid),
                "document_id": "claim-doc-1",
                "filename": "discharge_summary.pdf",
                "page_number": 3,
                "chunk_index": 0,
                "text": "Patient admitted with acute dengue fever.",
            }
        ],
        "policy_evidence": [
            {
                "chunk_id": str(policy_chunk_uuid),
                "clause_id": str(clause_uuid),
                "document_id": "policy-doc-1",
                "filename": "star_health_policy.pdf",
                "page_number": 7,
                "chunk_index": 2,
                "text": "Inpatient hospitalization covered up to sum insured.",
            }
        ],
    }
    retrieved = _retrieved_sources(state)

    finding = _make_finding(
        investigation_id=uuid4(),
        specialist="policy",
        finding_type="coverage_indicators[0]",
        data={
            "indicator": "Inpatient hospitalization is covered.",
            "supporting_evidence_ids": [
                str(claim_chunk_uuid),
                str(policy_chunk_uuid),
                claim_chunk_sha,
                unknown_id,
            ],
            "clause_id": str(clause_uuid),
            "confidence": "high",
        },
        retrieved=retrieved,
    )

    session = MagicMock()
    session.scalars.side_effect = [
        [claim_chunk_obj],
        [policy_chunk_obj],
    ]
    session.get.side_effect = lambda model, pk: (
        clause_obj if model is PolicyClause and pk == clause_uuid else None
    )

    _add_relational_references(session, [finding], retrieved)

    session.add_all.assert_called_once()
    added_refs: list[InvestigationFindingReference] = session.add_all.call_args.args[0]
    by_source_id = {ref.source_id: ref for ref in added_refs}

    # 1. Claim evidence chunk resolved by UUID primary key
    ref_claim_uuid = by_source_id[str(claim_chunk_uuid)]
    assert ref_claim_uuid.source_kind == "claim_evidence"
    assert ref_claim_uuid.claim_evidence_chunk_id == claim_chunk_uuid
    assert ref_claim_uuid.policy_chunk_id is None
    assert ref_claim_uuid.policy_clause_id is None
    assert ref_claim_uuid.provenance["filename"] == "discharge_summary.pdf"
    assert ref_claim_uuid.provenance["page_number"] == 3
    assert "acute dengue fever" in ref_claim_uuid.provenance["text"]

    # 2. Claim evidence chunk resolved by SHA-256 chunk_id
    ref_claim_sha = by_source_id[claim_chunk_sha]
    assert ref_claim_sha.source_kind == "claim_evidence"
    assert ref_claim_sha.claim_evidence_chunk_id == claim_chunk_uuid

    # 3. Policy chunk resolved by UUID primary key
    ref_policy_uuid = by_source_id[str(policy_chunk_uuid)]
    assert ref_policy_uuid.source_kind == "policy_chunk"
    assert ref_policy_uuid.policy_chunk_id == policy_chunk_uuid
    assert ref_policy_uuid.claim_evidence_chunk_id is None
    assert ref_policy_uuid.policy_clause_id is None
    assert ref_policy_uuid.provenance["filename"] == "star_health_policy.pdf"
    assert ref_policy_uuid.provenance["page_number"] == 7

    # 4. Policy clause resolved by UUID with full provenance from policy_evidence
    ref_clause = by_source_id[str(clause_uuid)]
    assert ref_clause.source_kind == "policy_clause"
    assert ref_clause.policy_clause_id == clause_uuid
    assert ref_clause.claim_evidence_chunk_id is None
    assert ref_clause.policy_chunk_id is None
    assert ref_clause.provenance["filename"] == "star_health_policy.pdf"
    assert ref_clause.provenance["page_number"] == 7

    # 5. Unknown ID remains unresolved without fabricated foreign keys
    ref_unknown = by_source_id[unknown_id]
    assert ref_unknown.source_kind == "unresolved"
    assert ref_unknown.claim_evidence_chunk_id is None
    assert ref_unknown.policy_chunk_id is None
    assert ref_unknown.policy_clause_id is None


def test_postgres_finding_reference_persistence_resolves_uuid_chunks() -> None:
    """End-to-end persistence test against claimsage_test PostgreSQL verifying
    that new investigation persistence resolves UUID chunk/clause IDs into
    relational foreign keys and preserves provenance.
    """
    from sqlalchemy import delete as sa_delete, select as sa_select
    from claimsage.db.session import SessionLocal

    suffix = uuid4().hex[:10]
    with SessionLocal() as session:
        employee = Employee(
            email=f"persist-ref-{suffix}@claimsage.local",
            display_name="Ref Test Adjuster",
            role=EmployeeRole.CLAIMS_ADJUSTER,
            team_id=f"team-{suffix}",
        )
        session.add(employee)
        session.flush()

        claim = Claim(
            claim_number=f"CLM-REF-{suffix}",
            claimant_name="Synthetic Patient",
            claim_type="health",
            status="under_review",
            assigned_employee_id=employee.id,
            team_id=employee.team_id,
            summary="Synthetic health claim for finding reference persistence test.",
        )
        policy_doc = PolicyDocument(
            filename=f"policy_{suffix}.pdf",
            checksum_sha256=f"sha256_policy_{suffix}",
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=employee.id,
            status="processed",
        )
        session.add_all([claim, policy_doc])
        session.flush()

        evidence_doc = ClaimEvidenceDocument(
            claim_id=claim.id,
            filename=f"hospital_bill_{suffix}.pdf",
            checksum_sha256=f"sha256_ev_{suffix}",
            mime_type="application/pdf",
            file_size_bytes=2048,
            uploaded_by_employee_id=employee.id,
            status="processed",
        )
        policy_chunk = PolicyChunk(
            document_id=policy_doc.id,
            chunk_id=f"pol_sha_{suffix}".ljust(64, "0"),
            page_number=4,
            chunk_index=1,
            text="Room rent covered up to 1% of sum insured per day.",
        )
        session.add_all([evidence_doc, policy_chunk])
        session.flush()

        evidence_chunk = ClaimEvidenceChunk(
            document_id=evidence_doc.id,
            chunk_id=f"ev_sha_{suffix}".ljust(64, "0"),
            page_number=2,
            chunk_index=0,
            text="Final inpatient bill total INR 68,500.",
        )
        policy_clause = PolicyClause(
            document_id=policy_doc.id,
            source_chunk_id=policy_chunk.id,
            clause_identifier=f"clause-{suffix}",
            clause_category="coverage",
            clause_text="Room rent covered up to 1% of sum insured per day.",
            source_page_number=4,
            verification_status="verified",
        )
        session.add_all([evidence_chunk, policy_clause])
        session.flush()

        run = create_investigation_run(
            session,
            claim=claim,
            employee_id=employee.id,
            task="Verify finding reference resolution with UUID chunk IDs.",
        )
        state = {
            "claim_id": str(claim.id),
            "claim_evidence": [
                {
                    "chunk_id": str(evidence_chunk.id),
                    "document_id": str(evidence_doc.id),
                    "filename": evidence_doc.filename,
                    "page_number": 2,
                    "chunk_index": 0,
                    "text": evidence_chunk.text,
                }
            ],
            "policy_evidence": [
                {
                    "chunk_id": str(policy_chunk.id),
                    "clause_id": str(policy_clause.id),
                    "document_id": str(policy_doc.id),
                    "filename": policy_doc.filename,
                    "page_number": 4,
                    "chunk_index": 1,
                    "text": policy_chunk.text,
                }
            ],
            "evidence_analysis": {
                "factual_findings": [
                    {
                        "finding": "Final inpatient bill total is INR 68,500.",
                        "supporting_evidence_ids": [str(evidence_chunk.id)],
                        "confidence": "high",
                    }
                ],
            },
            "policy_analysis": {
                "coverage_indicators": [
                    {
                        "indicator": "Room rent sub-limit applies.",
                        "supporting_evidence_ids": [str(policy_chunk.id)],
                        "clause_id": str(policy_clause.id),
                        "confidence": "high",
                    }
                ],
            },
            "review_report_status": "completed",
            "result": {
                "human_review_required": True,
                "review_report_status": "completed",
                "review_report": {
                    "overall_status": "completed",
                    "specialist_coverage": [],
                },
            },
        }

        finish_investigation(session, investigation=run, state=state)

        persisted_refs = session.scalars(
            sa_select(InvestigationFindingReference).where(
                InvestigationFindingReference.source_id.in_(
                    [
                        str(evidence_chunk.id),
                        str(policy_chunk.id),
                        str(policy_clause.id),
                    ]
                )
            )
        ).all()
        ref_map = {r.source_id: r for r in persisted_refs}

        assert ref_map[str(evidence_chunk.id)].source_kind == "claim_evidence"
        assert ref_map[str(evidence_chunk.id)].claim_evidence_chunk_id == evidence_chunk.id
        assert ref_map[str(evidence_chunk.id)].provenance["filename"] == evidence_doc.filename
        assert ref_map[str(evidence_chunk.id)].provenance["page_number"] == 2

        assert ref_map[str(policy_chunk.id)].source_kind == "policy_chunk"
        assert ref_map[str(policy_chunk.id)].policy_chunk_id == policy_chunk.id
        assert ref_map[str(policy_chunk.id)].provenance["filename"] == policy_doc.filename
        assert ref_map[str(policy_chunk.id)].provenance["page_number"] == 4

        assert ref_map[str(policy_clause.id)].source_kind == "policy_clause"
        assert ref_map[str(policy_clause.id)].policy_clause_id == policy_clause.id
        assert ref_map[str(policy_clause.id)].provenance["filename"] == policy_doc.filename
        assert ref_map[str(policy_clause.id)].provenance["page_number"] == 4

        # Clean up synthetic test records from claimsage_test
        session.execute(sa_delete(InvestigationRun).where(InvestigationRun.id == run.id))
        session.execute(sa_delete(ClaimEvidenceDocument).where(ClaimEvidenceDocument.id == evidence_doc.id))
        session.execute(sa_delete(Claim).where(Claim.id == claim.id))
        session.execute(sa_delete(PolicyDocument).where(PolicyDocument.id == policy_doc.id))
        session.execute(sa_delete(Employee).where(Employee.id == employee.id))
        session.commit()
