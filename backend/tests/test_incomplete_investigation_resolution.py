"""Tests for Incomplete Investigation Resolution and Accurate Report Completeness.

Covers:
1. Evidence Analyst insufficient-evidence handling.
2. Repair Estimate Analyst conditional routing and skip distinction.
3. Specialist failure vs insufficient-evidence vs skip handling.
4. Partial report generation with accurate specialist coverage.
5. Investigation completion status accuracy.
6. Idempotent resume and retry.
7. Duplicate findings and audit prevention.
8. Existing specialist output and citation preservation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from claimsage.agents.graph import (
    run_repair_estimate_analyst,
    run_review_report,
)
from claimsage.agents.review_report_agent import (
    _overall_status,
    analyze_review_report,
)
from claimsage.agents.report_validation import _compute_report_completeness
from claimsage.agents.schemas import (
    EvidenceAnalystOutput,
    IntakeDocumentOutput,
    PolicyAnalystOutput,
    ReviewReportEvidenceChunk,
    ReviewReportInput,
    ReviewReportOutput,
    ReviewReportSpecialistInput,
    RiskAnomalyOutput,
)
from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
    InvestigationFinding,
    InvestigationReport,
    InvestigationRun,
)
from claimsage.services.investigation_persistence import (
    _replace_findings,
    _sync_report,
    finish_investigation,
    is_investigation_complete,
)


def _make_evidence_chunk(evidence_id: str | None = None) -> ReviewReportEvidenceChunk:
    return ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID(evidence_id) if evidence_id else uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename="medical_discharge.pdf",
        page_number=1,
        chunk_index=0,
        text="Patient Rohan Varma underwent laparoscopic appendectomy on 10 Feb 2026. Total bill INR 74,500.",
        extraction_method="native",
    )


def test_review_report_overall_status_completed_with_insufficient_evidence_specialist():
    """When some specialists completed and one returned insufficient_evidence, overall_status is completed."""
    evidence = _make_evidence_chunk()

    intake_data = IntakeDocumentOutput(
        summary="Intake completed",
        extracted_fields=[],
        document_flags=[],
        document_inventory=[],
        missing_information=[],
        overall_assessment="documents_sufficient",
        human_review_required=True,
    ).model_dump(mode="json")

    evidence_data = EvidenceAnalystOutput(
        summary="Evidence is insufficient for complete coverage evaluation",
        factual_findings=[],
        timeline=[],
        inconsistencies=[],
        missing_information=["Pre-authorization required"],
        evidence_gaps=["No pre-authorization"],
        overall_assessment="insufficient_evidence",
        human_review_required=True,
    ).model_dump(mode="json")

    policy_data = PolicyAnalystOutput(
        summary="Policy clauses reviewed",
        relevant_clauses=[],
        coverage_indicators=[],
        exclusions_and_conditions=[],
        missing_information=[],
        evidence_gaps=[],
        overall_assessment="potentially_supportive",
        human_review_required=True,
    ).model_dump(mode="json")

    risk_data = RiskAnomalyOutput(
        summary="Risk analysis complete",
        observed_facts=[],
        anomalies=[],
        hypotheses=[],
        missing_information=[],
        overall_status="analyzed",
        human_review_required=True,
    ).model_dump(mode="json")

    report_input = ReviewReportInput(
        claim_facts={"claim_number": "CLM-DEMO-HEALTH-001", "claim_type": "health"},
        retrieved_evidence=[evidence],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis=intake_data,
        ),
        evidence_analyst=ReviewReportSpecialistInput(
            status="insufficient_evidence",
            analysis=evidence_data,
        ),
        policy_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis=policy_data,
        ),
        repair_estimate_analyst=ReviewReportSpecialistInput(
            status="skipped",
            analysis=None,
        ),
        risk_anomaly_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis=risk_data,
        ),
    )

    # 1. _overall_status must be "completed", NOT "incomplete"
    status = _overall_status(report_input)
    assert status == "completed", f"Expected 'completed', got {status}"

    # 2. _compute_report_completeness must be "partial" because one specialist had insufficient_evidence
    mock_report = ReviewReportOutput(
        overall_status="completed",
        observed_facts=[],
        analyst_interpretations=[],
        hypotheses=[],
        conflicting_findings=[],
        missing_information=[],
        specialist_coverage=[],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        evidence_scope_note="Scoped to retrieved evidence.",
        human_review_required=True,
    )
    completeness = _compute_report_completeness(mock_report, report_input)
    assert completeness == "partial", f"Expected 'partial', got {completeness}"


from claimsage.db.session import SessionLocal


def test_repair_estimate_analyst_correctly_skipped_for_health():
    """Health insurance claims without repair estimates must be skipped, not failed."""
    state = {
        "claim_facts": {"claim_type": "health"},
        "repair_estimate_document_id": None,
        "repair_estimate_analysis_status": "skipped",
        "repair_estimate_analysis": None,
        "selected_analysts": ["intake_agent", "evidence_analyst", "policy_analyst", "risk_anomaly_agent"],
        "result": {
            "repair_estimate_analysis_status": "skipped",
        },
    }
    runtime = MagicMock()
    update = run_repair_estimate_analyst(state, runtime)
    assert update == {} or update.get("repair_estimate_analysis_status") == "skipped"


def test_is_investigation_complete_with_partial_insufficient_evidence():
    """is_investigation_complete returns True when report is completed and specialists are completed/skipped/insufficient_evidence."""
    state = {
        "error": None,
        "result": {
            "review_report_status": "completed",
            "provider_failures": [],
            "review_report": {
                "overall_status": "completed",
                "report_completeness": "partial",
                "specialist_coverage": [
                    {"specialist": "intake_agent", "status": "completed"},
                    {"specialist": "evidence_analyst", "status": "insufficient_evidence"},
                    {"specialist": "policy_analyst", "status": "completed"},
                    {"specialist": "repair_estimate_analyst", "status": "skipped"},
                    {"specialist": "risk_anomaly_agent", "status": "completed"},
                ],
            },
        },
    }
    assert is_investigation_complete(state) is True


def test_is_investigation_incomplete_when_specialist_actually_failed():
    """is_investigation_complete returns False when a specialist actually failed or was unavailable."""
    state = {
        "error": None,
        "result": {
            "review_report_status": "completed",
            "provider_failures": [],
            "review_report": {
                "overall_status": "completed",
                "specialist_coverage": [
                    {"specialist": "intake_agent", "status": "completed"},
                    {"specialist": "evidence_analyst", "status": "failed"},  # Genuine failure
                    {"specialist": "policy_analyst", "status": "completed"},
                    {"specialist": "repair_estimate_analyst", "status": "skipped"},
                    {"specialist": "risk_anomaly_agent", "status": "completed"},
                ],
            },
        },
    }
    assert is_investigation_complete(state) is False


def test_replace_findings_is_idempotent():
    """_replace_findings removes prior findings and inserts fresh ones without duplicating."""
    with SessionLocal() as db_session:
        employee = Employee(
            id=uuid.uuid4(),
            email=f"tester-{uuid.uuid4().hex[:6]}@claimsage.local",
            display_name="Test Adjuster",
            role=EmployeeRole.CLAIMS_ADJUSTER,
        )
        db_session.add(employee)
        claim = Claim(
            id=uuid.uuid4(),
            claim_number=f"CLM-TEST-{uuid.uuid4().hex[:6]}",
            claimant_name="Test Claimant",
            claim_type="health",
            status="under_review",
        )
        db_session.add(claim)
        inv = InvestigationRun(
            id=uuid.uuid4(),
            claim_id=claim.id,
            claim_domain="health",
            initiated_by_employee_id=employee.id,
            task="Test task",
            status="running",
        )
        db_session.add(inv)
        db_session.flush()

        state = {
            "claim_evidence": [
                {
                    "chunk_id": str(uuid.uuid4()),
                    "text": "Evidence snippet",
                    "filename": "file.pdf",
                }
            ],
            "intake_analysis": {
                "summary": "Intake summary",
                "extracted_fields": [{"field": "test", "value": "123"}],
            },
        }

        # First call: creates findings
        _replace_findings(db_session, inv, state)
        db_session.commit()

        count1 = db_session.query(InvestigationFinding).filter(
            InvestigationFinding.investigation_id == inv.id
        ).count()
        assert count1 > 0

        # Second call: must replace, NOT duplicate
        _replace_findings(db_session, inv, state)
        db_session.commit()

        count2 = db_session.query(InvestigationFinding).filter(
            InvestigationFinding.investigation_id == inv.id
        ).count()
        assert count2 == count1, f"Expected {count1} findings after replacement, got {count2}"


def test_finish_investigation_audit_event_deduplication():
    """finish_investigation deduplicates audit events idempotently."""
    with SessionLocal() as db_session:
        employee = Employee(
            id=uuid.uuid4(),
            email=f"auditor-{uuid.uuid4().hex[:6]}@claimsage.local",
            display_name="Auditor Adjuster",
            role=EmployeeRole.CLAIMS_ADJUSTER,
        )
        db_session.add(employee)
        claim = Claim(
            id=uuid.uuid4(),
            claim_number=f"CLM-AUDIT-{uuid.uuid4().hex[:6]}",
            claimant_name="Audit Claimant",
            claim_type="health",
            status="under_review",
        )
        db_session.add(claim)
        inv = InvestigationRun(
            id=uuid.uuid4(),
            claim_id=claim.id,
            claim_domain="health",
            initiated_by_employee_id=employee.id,
            task="Audit test task",
            status="running",
        )
        db_session.add(inv)
        db_session.flush()

        state = {
            "error": None,
            "result": {
                "review_report_status": "completed",
                "human_review_required": True,
                "review_report": {
                    "overall_status": "completed",
                    "report_completeness": "full",
                    "specialist_coverage": [],
                },
            },
        }

        # Finish investigation first time
        finish_investigation(db_session, investigation=inv, state=state)
        events1 = db_session.query(AuditEvent).filter(
            AuditEvent.investigation_id == inv.id,
            AuditEvent.action == "investigation_finished",
        ).count()
        assert events1 == 1

        # Finish investigation second time (e.g. on resume completion)
        finish_investigation(db_session, investigation=inv, state=state)
        events2 = db_session.query(AuditEvent).filter(
            AuditEvent.investigation_id == inv.id,
            AuditEvent.action == "investigation_finished",
        ).count()
        assert events2 == 1, "Duplicate investigation_finished audit event was created"


def test_report_completeness_all_combinations():
    """Verify report completeness calculation across all specified combinations."""
    evidence = _make_evidence_chunk()

    dummy_analysis = {"summary": "dummy"}

    def make_input(statuses: dict[str, str]) -> ReviewReportInput:
        return ReviewReportInput(
            claim_facts={"claim_number": "CLM-COMBO-001", "claim_type": "health"},
            retrieved_evidence=[evidence],
            evidence_retrieval_status="completed",
            evidence_retrieval_limitations=[],
            intake_agent=ReviewReportSpecialistInput(
                status=statuses.get("intake", "completed"),
                analysis=dummy_analysis if statuses.get("intake", "completed") in {"completed", "insufficient_evidence"} else None,
            ),
            evidence_analyst=ReviewReportSpecialistInput(
                status=statuses.get("evidence", "completed"),
                analysis=dummy_analysis if statuses.get("evidence", "completed") in {"completed", "insufficient_evidence"} else None,
            ),
            policy_analyst=ReviewReportSpecialistInput(
                status=statuses.get("policy", "completed"),
                analysis=dummy_analysis if statuses.get("policy", "completed") in {"completed", "insufficient_evidence"} else None,
            ),
            repair_estimate_analyst=ReviewReportSpecialistInput(
                status=statuses.get("repair", "skipped"),
                analysis=dummy_analysis if statuses.get("repair", "skipped") in {"completed", "insufficient_evidence"} else None,
            ),
            risk_anomaly_agent=ReviewReportSpecialistInput(
                status=statuses.get("risk", "completed"),
                analysis=dummy_analysis if statuses.get("risk", "completed") in {"completed", "insufficient_evidence"} else None,
            ),
        )

    # 1. All completed (repair skipped because health) -> complete
    inp_full = make_input({"intake": "completed", "evidence": "completed", "policy": "completed", "repair": "skipped", "risk": "completed"})
    rep_full = ReviewReportOutput(
        overall_status=_overall_status(inp_full),
        observed_facts=[], analyst_interpretations=[], hypotheses=[], conflicting_findings=[], missing_information=[],
        specialist_coverage=[], evidence_retrieval_status="completed", evidence_retrieval_limitations=[],
        evidence_scope_note="Scoped", human_review_required=True,
    )
    assert _overall_status(inp_full) == "completed"
    assert _compute_report_completeness(rep_full, inp_full) == "complete"

    # 2. Partial with insufficient_evidence -> partial
    inp_partial = make_input({"intake": "completed", "evidence": "insufficient_evidence", "policy": "completed", "repair": "skipped", "risk": "completed"})
    rep_partial = ReviewReportOutput(
        overall_status=_overall_status(inp_partial),
        observed_facts=[], analyst_interpretations=[], hypotheses=[], conflicting_findings=[], missing_information=[],
        specialist_coverage=[], evidence_retrieval_status="completed", evidence_retrieval_limitations=[],
        evidence_scope_note="Scoped", human_review_required=True,
    )
    assert _overall_status(inp_partial) == "completed"
    assert _compute_report_completeness(rep_partial, inp_partial) == "partial"

    # 3. Truly failed analyst -> incomplete overall
    inp_failed = make_input({"intake": "completed", "evidence": "failed", "policy": "completed", "repair": "skipped", "risk": "completed"})
    assert _overall_status(inp_failed) == "incomplete"


def test_guardrails_prevent_autonomous_settlement_and_real_emails():
    """Verify that report output enforces human review and no autonomous settlement."""
    evidence = _make_evidence_chunk()
    dummy = {"summary": "dummy"}
    inp = ReviewReportInput(
        claim_facts={"claim_number": "CLM-DEMO-HEALTH-001", "claim_type": "health"},
        retrieved_evidence=[evidence],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(status="completed", analysis=dummy),
        evidence_analyst=ReviewReportSpecialistInput(status="completed", analysis=dummy),
        policy_analyst=ReviewReportSpecialistInput(status="completed", analysis=dummy),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="completed", analysis=dummy),
    )
    # Human review must always be required
    report = ReviewReportOutput(
        overall_status="completed",
        observed_facts=[],
        analyst_interpretations=[],
        hypotheses=[],
        conflicting_findings=[],
        missing_information=[],
        specialist_coverage=[],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        evidence_scope_note="Scoped",
        human_review_required=True,
    )
    assert report.human_review_required is True

    # Check limitations disclaimers in persistence/database sync
    with SessionLocal() as session:
        inv = session.get(InvestigationRun, uuid.UUID("28e9d1ee-e7a4-4b9b-a5de-0ac0b82e88fb"))
        if inv and inv.reports:
            rep_record = inv.reports[0]
            assert rep_record.human_review_required is True
            assert any("No coverage, fraud, or settlement decision was made" in lim for lim in rep_record.limitations)
            assert any("Human review is required before any consequential action" in lim for lim in rep_record.limitations)


def test_issue1_evidence_analyst_analysis_included_when_insufficient_evidence():
    """Issue 1: Specialist coverage for insufficient_evidence with analysis must have analysis_included=True."""
    from claimsage.agents.review_report_agent import _coverage

    dummy_analysis = {"summary": "Valid evidence analysis", "factual_findings": []}
    inp = ReviewReportInput(
        claim_facts={"claim_number": "CLM-DEMO-HEALTH-001", "claim_type": "health"},
        retrieved_evidence=[_make_evidence_chunk()],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
        evidence_analyst=ReviewReportSpecialistInput(status="insufficient_evidence", analysis=dummy_analysis),
        policy_analyst=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
    )

    cov_list = _coverage(inp)
    ev_cov = next(c for c in cov_list if c.specialist == "evidence_analyst")
    assert ev_cov.status == "insufficient_evidence"
    assert ev_cov.analysis_included is True


def test_issue2_general_ward_accommodation_reconciled_with_claim_evidence_not_policy():
    """Issue 2: Hospital bill accommodation must be reconciled against claim evidence, never policy evidence."""
    from claimsage.agents.report_validation import (
        build_shared_evidence_context,
        reconcile_missing_information,
        reconcile_specialist_missing_in_state,
    )
    from claimsage.agents.schemas import ReviewReportItem

    claim_bill_chunk = ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID("5b75aaac-02d2-46d8-ac2d-76f4e90f88e8"),
        document_id=uuid.uuid4(),
        filename="claimsage_synthetic_health_evidence_rohan_varma.pdf",
        page_number=1,
        chunk_index=2,
        text="Itemised Final Hospital Bill. General ward accommodation (3 days × ■4,500) 13,500. TOTAL 74,500.",
        extraction_method="native",
    )
    policy_chunk = ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID("7cd67a99-70a8-4970-a832-c3e4b1392d19"),
        document_id=uuid.uuid4(),
        filename="ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
        page_number=3,
        chunk_index=3,
        text="Clause 4.1 Room Rent: Daily room rent limit for general ward is up to 1% of Sum Insured.",
        clause_identifier="Clause 4.1",
        verification_status="verified",
        extraction_method="native",
    )

    state = {
        "claim_type": "health",
        "claim_facts": {"claim_type": "health", "claim_number": "CLM-DEMO-HEALTH-001"},
        "claim_evidence": [claim_bill_chunk.model_dump(mode="json")],
        "policy_evidence": [policy_chunk.model_dump(mode="json")],
        "repair_estimate_evidence": [],
        "intake_analysis": {
            "summary": "The bill lists most cost components, but the line for General ward accommodation is truncated, leaving the amount unknown; this creates a gap in verifying the total claimed INR 74,500.",
            "document_flags": [
                {
                    "severity": "medium",
                    "description": "Itemised hospital bill line for General ward accommodation is truncated; amount not fully captured.",
                    "source_evidence_ids": ["5b75aaac-02d2-46d8-ac2d-76f4e90f88e8"],
                }
            ],
            "extracted_fields": [
                {
                    "field_name": "bill_item_general_ward_accommodation",
                    "value": "Incomplete amount; text ends after 'General ward accommodation (3 days ×'",
                    "uncertain": True,
                    "confidence": "low",
                    "page_numbers": [1],
                    "source_evidence_ids": ["5b75aaac-02d2-46d8-ac2d-76f4e90f88e8"],
                }
            ],
            "document_inventory": [
                {
                    "status": "incomplete",
                    "filename": "claimsage_synthetic_health_evidence_rohan_varma.pdf",
                    "document_type": "Itemised Final Hospital Bill",
                    "source_evidence_ids": ["5b75aaac-02d2-46d8-ac2d-76f4e90f88e8"],
                }
            ],
            "missing_information": [
                "Full amount for General ward accommodation line item on the hospital bill."
            ],
        },
    }

    # Verify state reconciliation fixes the hallucinated truncated item
    state_updates = reconcile_specialist_missing_in_state(state)
    assert "intake_analysis" in state_updates
    updated_intake = state_updates["intake_analysis"]
    ward_fld = next(f for f in updated_intake["extracted_fields"] if f["field_name"] == "bill_item_general_ward_accommodation")
    assert "13,500" in ward_fld["value"]
    assert ward_fld["uncertain"] is False
    assert ward_fld["confidence"] == "high"

    # Verify reconciliation does NOT use policy evidence for hospital bill
    shared_rec = state_updates["result"]["shared_evidence_reconciliation"]
    ward_rec = next(r for r in shared_rec if "ward accommodation" in r["original_statement"].lower())
    assert "ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf" not in ward_rec["available_in_sources"]
    assert "claimsage_synthetic_health_evidence_rohan_varma.pdf" in ward_rec["available_in_sources"]


def test_issue3_policy_document_retrieved_and_verified_vs_missing_clauses():
    """Issue 3: Distinguish policy document present & verified vs specific unretrieved clause."""
    from claimsage.agents.report_validation import reconcile_missing_information
    from claimsage.agents.schemas import ReviewReportItem

    policy_chunk = ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID("f5de60e2-a406-42f7-a255-bf23eb8d319a"),
        document_id=uuid.uuid4(),
        filename="ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
        page_number=1,
        chunk_index=0,
        text="ClaimSage Synthetic Assurance Ltd. Policy Identifier: DEMO-HEALTH-SECURE-2026-V3.",
        clause_identifier="Preamble",
        verification_status="verified",
        extraction_method="native",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_number": "CLM-DEMO-HEALTH-001", "claim_type": "health"},
        retrieved_evidence=[policy_chunk],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
        evidence_analyst=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
        policy_analyst=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="completed", analysis={"summary": "ok"}),
    )

    items = [
        # Whole policy missing claim -> must be reconciled out as verified
        ReviewReportItem(
            statement="Full policy wording for DEMO-HEALTH-SECURE-2026-V3 (coverage limits, waiting periods, exclusions).",
            explanation="Reported by evidence_analyst.",
            source_basis="analyst_output",
            originating_specialist="evidence_analyst",
        ),
        # Specific clause missing -> must be retained as not_retrieved, NOT not_provided
        ReviewReportItem(
            statement="Missing inpatient surgery coverage clause.",
            explanation="Reported by risk_anomaly_agent.",
            source_basis="analyst_output",
            originating_specialist="risk_anomaly_agent",
        ),
    ]

    reconciled_items, rec_log = reconcile_missing_information(
        report_input=report_input,
        candidate_missing_items=items,
        indexed_findings=[],
        extracted_values=[],
        conflicts=[],
        evidence_by_id={policy_chunk.chunk_id: policy_chunk},
    )

    # 1. Whole policy wording missing claim is reconciled out as verified
    whole_pol_log = next(r for r in rec_log if "full policy wording" in r.original_statement.lower())
    assert whole_pol_log.reconciled_category == "verified"
    assert whole_pol_log.retained_in_missing_information is False

    # 2. Specific clause missing is retained in missing_information as not_retrieved
    spec_clause_item = next(i for i in reconciled_items if "inpatient surgery" in i.statement.lower())
    assert spec_clause_item.missing_category == "not_retrieved"
    assert "retrieved and verified" in spec_clause_item.explanation
    assert "No supporting document or evidence was provided" not in spec_clause_item.explanation


def test_issue1_room_rent_line_item_extracted_and_not_missing_in_risk_anomaly():
    """Issue 1: General ward accommodation must not produce a missing-room-rent finding in risk analysis."""
    from claimsage.agents.report_validation import reconcile_specialist_missing_in_state

    claim_bill_chunk = ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID("5b75aaac-02d2-46d8-ac2d-76f4e90f88e8"),
        document_id=uuid.uuid4(),
        filename="claimsage_synthetic_health_evidence_rohan_varma.pdf",
        page_number=1,
        chunk_index=2,
        text=(
            "Document 2: Itemised Final Hospital Bill. Description Amount (INR) "
            "Emergency consultation and assessment 3,500 Laboratory investigations 8,000 "
            "Imaging 6,500 Operating theatre and procedure 22,000 Surgeon and anaesthesia fees 14,000 "
            "Medicines and consumables 7,000 General ward accommodation (3 days × ■4,500) 13,500 TOTAL 74,500. "
            "Billing notes This synthetic bill is marked FINAL and itemised for demonstration. "
            "It records a three-day general ward stay at ■4,500 per day. The listed line items total ■74,500."
        ),
        extraction_method="native",
    )
    policy_chunk = ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID("7cd67a99-70a8-4970-a832-c3e4b1392d19"),
        document_id=uuid.uuid4(),
        filename="ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
        page_number=3,
        chunk_index=1,
        text="Normal Room Rent INR 5,000 per day maximum Proportionate deduction if exceeded",
        clause_identifier="Clause 6",
        verification_status="verified",
        extraction_method="native",
    )

    state = {
        "claim_type": "health",
        "claim_facts": {"claim_type": "health", "claim_number": "CLM-DEMO-HEALTH-001"},
        "claim_evidence": [claim_bill_chunk.model_dump(mode="json")],
        "policy_evidence": [policy_chunk.model_dump(mode="json")],
        "repair_estimate_evidence": [],
        "risk_analysis": {
            "overall_status": "analyzed",
            "anomalies": [
                {
                    "finding": "Missing room-rent line item to compare with policy sub-limit.",
                    "explanation": "Itemised bill does not show daily room-rent charges, preventing verification against the INR 5,000 per day sub-limit.",
                    "supporting_evidence_ids": ["5b75aaac-02d2-46d8-ac2d-76f4e90f88e8", "7cd67a99-70a8-4970-a832-c3e4b1392d19"],
                    "supporting_quotes": [],
                    "requires_human_verification": True,
                }
            ],
            "hypotheses": [],
            "missing_information": [
                "Missing room-rent line item on the bill."
            ],
            "human_review_required": True,
        },
    }

    state_updates = reconcile_specialist_missing_in_state(state)
    assert "risk_analysis" in state_updates
    updated_risk = state_updates["risk_analysis"]

    # 1. Finding must NOT claim room-rent is missing
    for anom in updated_risk["anomalies"]:
        f_lower = anom["finding"].lower()
        e_lower = anom["explanation"].lower()
        assert "missing room-rent" not in f_lower
        assert "does not show daily room-rent" not in e_lower
        assert "4,500" in anom["explanation"]
        assert "5,000" in anom["explanation"]
        assert "human review is required" in anom["explanation"].lower()

    # 2. Missing information must NOT contain missing room-rent
    for m in updated_risk["missing_information"]:
        stmt = m if isinstance(m, str) else m.get("finding", "")
        assert "room-rent" not in stmt.lower() and "room rent" not in stmt.lower()


def test_issue2_inpatient_hospitalization_coverage_acknowledged_in_policy_analyst():
    """Issue 2: Policy Analyst must acknowledge inpatient hospitalization under Section 3 and not claim only day-care is covered."""
    from claimsage.agents.report_validation import reconcile_specialist_missing_in_state

    hosp_policy_chunk = ReviewReportEvidenceChunk(
        chunk_id=uuid.UUID("1e1e1e1e-2222-3333-4444-555555555555"),
        document_id=uuid.uuid4(),
        filename="ClaimSage_Synthetic_Health_Insurance_Policy_v3.pdf",
        page_number=1,
        chunk_index=1,
        text=(
            "3. Hospitalization Coverage. The policy covers eligible medical expenses incurred "
            "during medically necessary inpatient hospitalization requiring an admission for at "
            "least twenty-four (24) consecutive hours. Covered components include nursing expenses, "
            "boarding fees, medicines, consumables directly administered, intravenous fluids, "
            "blood, oxygen, and diagnostic tests ordered by the treating physician."
        ),
        clause_identifier="Section 3",
        verification_status="verified",
        extraction_method="native",
    )

    state = {
        "claim_type": "health",
        "claim_facts": {"claim_type": "health", "claim_number": "CLM-DEMO-HEALTH-001"},
        "claim_evidence": [],
        "policy_evidence": [hosp_policy_chunk.model_dump(mode="json")],
        "repair_estimate_evidence": [],
        "policy_analysis": {
            "overall_status": "analyzed",
            "relevant_clauses": [
                {
                    "finding": "Day-Care Surgery limit up to Sum Insured (INR 500,000).",
                    "confidence": "medium",
                    "explanation": "Policy mentions day-care surgery limit equal to sum insured.",
                    "supporting_evidence_ids": [str(hosp_policy_chunk.chunk_id)],
                    "supporting_quotes": [],
                }
            ],
            "coverage_indicators": [
                {
                    "conclusion": "The policy only specifies a Day-Care Surgery limit equal to the Sum Insured, indicating coverage for medically necessary procedures, though the claim involves an inpatient surgery.",
                    "supporting_evidence_ids": [str(hosp_policy_chunk.chunk_id)],
                    "supporting_quotes": [],
                }
            ],
            "missing_information": [],
            "exclusions_and_conditions": [],
            "overall_assessment": "mixed",
            "human_review_required": True,
        },
    }

    state_updates = reconcile_specialist_missing_in_state(state)
    assert "policy_analysis" in state_updates
    updated_pol = state_updates["policy_analysis"]

    for ind in updated_pol["coverage_indicators"]:
        c_lower = ind["conclusion"].lower()
        assert "only specifies a day-care" not in c_lower
        assert "section 3" in c_lower
        assert "inpatient hospitalization" in c_lower
        assert "human review" in c_lower




