"""Regression test suite for ClaimSage Comprehensive Investigation Reliability Fix.

Covers all 17 required scenarios:
1. HTTP 429 and Retry-After handling (including multiple reset headers).
2. Safe report-stage retry and specialist-result preservation without rerunning completed specialists.
3. Configured fallback model behavior on HTTP 429 rate_limit_exceeded and fallback failure diagnostics.
4. Repair estimate quantity extraction (explicit quantities vs unit labels).
5. Missing quantities and invalid calculations (retaining unit price & reported amount without fabricating quantity=1).
6. Parts and labour classification and category subtotals.
7. Subtotal and total reconciliation against printed gross/depreciation/deductible/net totals.
8. Missing information found in another document.
9. Retrieved but unverified policy clauses (pending_review).
10. Specialist-specific document retrieval (repair_estimate_evidence channel).
11. Photograph and estimate source inventory lifecycle (uploaded, retrieved, used, uploaded_not_retrieved).
12. Duplicate source prevention (document inventory deduplication & repair line-item duplicate detection with missing quantity).
13. Conflicting financial amounts across documents.
14. Multiple claimants and concurrent investigations isolation.
15. Health insurance investigations end-to-end report validation.
16. Motor insurance investigations end-to-end report validation.
17. AI-generated and fallback report validation (including repair estimate calculation warnings).
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from claimsage.agents import graph as graph_module
from claimsage.agents import llm as llm_module
from claimsage.agents import repair_estimate_analyst as estimate_analyst_module
from claimsage.agents import review_report_agent as report_module
from claimsage.agents.repair_estimate_analyst import analyze_repair_estimate
from claimsage.agents.repair_estimate_rules import (
    EstimateLineItem,
    calculate_repair_estimate,
    classify_line_item_category,
    normalize_currency_and_decimal,
)
from claimsage.agents.review_report_agent import (
    ReviewReportAgentError,
    analyze_review_report,
    build_fallback_partial_report,
)
from claimsage.agents.schemas import (
    ClaimEvidenceFinding,
    EvidenceAnalystOutput,
    IntakeDocumentOutput,
    IntakeExtractedField,
    PolicyAnalystOutput,
    PolicyClauseFinding,
    PolicyEvidenceQuote,
    RepairEstimateExtractedLineItem,
    RepairEstimateExtraction,
    ReviewReportAnalystOutputReference,
    ReviewReportEvidenceChunk,
    ReviewReportEvidenceQuote,
    ReviewReportExtraction,
    ReviewReportInput,
    ReviewReportItemExtraction,
    ReviewReportSpecialistInput,
    RiskAnomalyOutput,
    SupervisorPlan,
)
from claimsage.services.investigation_persistence import is_investigation_complete


class _DummySchema(BaseModel):
    status: str = "ok"


def _mock_settings(**overrides: object) -> SimpleNamespace:
    base = {
        "app_env": "test",
        "groq_api_key": SecretStr("gsk_test_dummy_key_for_reliability_suite"),
        "groq_model": "openai/gpt-oss-120b",
        "groq_fallback_model": None,
        "llm_temperature": 0.0,
        "groq_timeout_seconds": 30.0,
        "groq_max_input_tokens": 24000,
        "groq_max_output_tokens": 4096,
        "groq_tokenizer_encoding": "o200k_harmony",
        "groq_max_retries": 2,
        "groq_max_retry_delay_seconds": 15.0,
        "groq_concurrency_limit": 2,
        "groq_pacing_delay_seconds": 0.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# 1. HTTP 429 and Retry-After Handling
# ---------------------------------------------------------------------------


def test_01_http_429_and_retry_after_header_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify multi-header 429 reset parsing selects the longest reset window and records cooldown."""
    monkeypatch.setattr(llm_module, "get_settings", lambda: _mock_settings())
    sleeps: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", lambda s: sleeps.append(s))
    mock_limiter = MagicMock()
    monkeypatch.setattr(llm_module, "get_shared_rate_limiter", lambda: mock_limiter)

    err_429 = type(
        "MultiHeader429",
        (RuntimeError,),
        {
            "status_code": 429,
            "code": "rate_limit_exceeded",
            "headers": {
                "Retry-After": "4.0",
                "X-RateLimit-Reset-Requests": "150ms",
                "X-RateLimit-Reset-Tokens": "19.5s",
                "X-Should-Retry": "true",
            },
        },
    )()

    meta = llm_module.safe_retry_metadata(err_429)
    assert meta["retry_after_seconds"] == 19.5
    assert meta["provider_retry_hint"] is True

    runnable = MagicMock()
    runnable.invoke.side_effect = [err_429, _DummySchema(status="recovered")]

    res = llm_module.invoke_structured(
        runnable,
        messages=[("system", "Test"), ("human", "Prompt")],
        output_schema=_DummySchema,
        stage="review_report",
    )
    assert res.status == "recovered"
    assert sleeps == [19.5]
    mock_limiter.record_provider_cooldown.assert_called_once_with(19.5)


# ---------------------------------------------------------------------------
# 2. Safe Report-Stage Retry and Specialist-Result Preservation
# ---------------------------------------------------------------------------


def test_02_safe_report_stage_retry_preserves_completed_specialists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify resuming an investigation or retrying only the failed report stage never reruns completed specialists."""
    emp_id = uuid4()
    claim_id = uuid4()
    ev_id = str(uuid4())
    doc_id = str(uuid4())

    claim_chunk = {
        "chunk_id": ev_id,
        "document_id": doc_id,
        "filename": "discharge_summary.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": "Admission Date: 2026-04-10. Final Hospital Bill: INR 48,000.",
        "similarity": 0.91,
        "embedding_model": "test-model",
        "extraction_method": "native",
        "ocr_confidence": None,
    }

    intake_out = IntakeDocumentOutput(
        summary="Extracted admission date.",
        extracted_fields=[
            IntakeExtractedField(
                field_name="Admission Date",
                value="2026-04-10",
                source_evidence_ids=[ev_id],
                page_numbers=[1],
                confidence="high",
            )
        ],
        overall_assessment="documents_sufficient",
        human_review_required=True,
    ).model_dump(mode="json")

    evidence_out = EvidenceAnalystOutput(
        summary="Hospital admission verified.",
        factual_findings=[
            ClaimEvidenceFinding(
                finding="Admission Date: 2026-04-10.",
                supporting_evidence_ids=[ev_id],
                explanation="Confirmed in discharge summary.",
                confidence="high",
            )
        ],
        overall_assessment="supportive",
        human_review_required=True,
    ).model_dump(mode="json")

    # Saved snapshot where specialists succeeded but review_report failed with 429
    saved_snapshot = {
        "employee_id": str(emp_id),
        "claim_id": str(claim_id),
        "task": "Investigate claim.",
        "claim_facts": {
            "claim_id": str(claim_id),
            "claim_type": "health",
            "status": "under_review",
            "loss_date": "2026-04-10",
        },
        "policy_evidence": [],
        "policy_retrieval_status": "no_applicable_policy",
        "policy_analysis": None,
        "policy_analysis_status": "skipped",
        "ai_analysis_status": "skipped",
        "claim_evidence": [claim_chunk],
        "claim_evidence_retrieval_status": "completed",
        "intake_analysis": intake_out,
        "intake_analysis_status": "completed",
        "evidence_analysis": evidence_out,
        "evidence_analysis_status": "completed",
        "repair_estimate_document_id": None,
        "repair_estimate_analysis": None,
        "repair_estimate_analysis_status": "skipped",
        "repair_estimate_evidence": [],
        "risk_analysis": None,
        "risk_analysis_status": "skipped",
        "selected_analysts": ["intake_agent", "evidence_analyst"],
        "supervisor_plan": {
            "selected_analysts": ["intake_agent", "evidence_analyst"],
            "routing_rationale": "Standard health review.",
            "human_review_required": True,
        },
        "supervisor_status": "completed",
        "review_report": None,
        "review_report_status": "unavailable",
        "result": {
            "task": "Investigate claim.",
            "claim": {"claim_id": str(claim_id), "claim_type": "health"},
            "claim_evidence": [claim_chunk],
            "claim_evidence_retrieval_status": "completed",
            "policy_evidence": [],
            "policy_retrieval_status": "no_applicable_policy",
            "supervisor_status": "completed",
            "intake_analysis": intake_out,
            "intake_analysis_status": "completed",
            "evidence_analysis": evidence_out,
            "evidence_analysis_status": "completed",
            "policy_analysis": None,
            "policy_analysis_status": "skipped",
            "ai_analysis_status": "skipped",
            "repair_estimate_analysis": None,
            "repair_estimate_analysis_status": "skipped",
            "risk_analysis": None,
            "risk_analysis_status": "skipped",
            "review_report": None,
            "review_report_status": "unavailable",
            "provider_failures": [
                {"stage": "review_report", "category": "rate_limited", "status_code": 429}
            ],
            "limitations": [
                "Review & Report generation is temporarily unavailable. Specialist results were retained for mandatory human review."
            ],
            "human_review_required": True,
        },
        "error": None,
    }

    assert is_investigation_complete(saved_snapshot) is False

    # Spy on all upstream specialists to ensure NONE of them are called during resumption
    spy_supervisor = MagicMock(side_effect=AssertionError("Supervisor should not rerun"))
    spy_intake = MagicMock(side_effect=AssertionError("Intake should not rerun"))
    spy_evidence = MagicMock(side_effect=AssertionError("Evidence should not rerun"))
    monkeypatch.setattr(graph_module, "create_supervisor_plan", spy_supervisor)
    monkeypatch.setattr(graph_module, "analyze_claim_documents", spy_intake)
    monkeypatch.setattr(graph_module, "analyze_claim_evidence", spy_evidence)

    # Mock review_report LLM to succeed on resumption
    structured = MagicMock()
    structured.invoke.return_value = ReviewReportExtraction(
        observed_facts=[
            ReviewReportItemExtraction(
                statement="Admission Date: 2026-04-10.",
                explanation="Verified in discharge summary.",
                supporting_evidence_ids=[ev_id],
                supporting_quotes=[
                    ReviewReportEvidenceQuote(
                        evidence_id=ev_id,
                        quote="Admission Date: 2026-04-10.",
                    )
                ],
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="evidence_analyst",
                        output_path="/factual_findings/0/finding",
                        finding_text="Admission Date: 2026-04-10.",
                    )
                ],
            )
        ]
    )
    chat_model = MagicMock()
    chat_model.with_structured_output.return_value = structured
    monkeypatch.setattr(report_module, "get_chat_model", lambda: chat_model)

    resumed_state = graph_module.run_investigation(
        session=MagicMock(spec=Session),
        employee_id=emp_id,
        claim_id=claim_id,
        task="Investigate claim.",
        resume_state=saved_snapshot,
    )

    spy_supervisor.assert_not_called()
    spy_intake.assert_not_called()
    spy_evidence.assert_not_called()
    assert resumed_state["intake_analysis"] == intake_out
    assert resumed_state["evidence_analysis"] == evidence_out
    assert resumed_state["review_report_status"] == "completed"
    assert resumed_state["result"]["provider_failures"] == []
    assert is_investigation_complete(resumed_state) is True


# ---------------------------------------------------------------------------
# 3. Configured Fallback Model Behavior
# ---------------------------------------------------------------------------


def test_03_configured_fallback_model_on_429_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify configured fallback model is used when primary model exhausts retries on HTTP 429."""
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: _mock_settings(
            groq_fallback_model="llama-3.3-70b-versatile",
            groq_max_retries=1,
        ),
    )
    monkeypatch.setattr(llm_module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(llm_module, "get_shared_rate_limiter", lambda: MagicMock())

    err_429 = type(
        "RateLimitErr",
        (RuntimeError,),
        {
            "status_code": 429,
            "code": "rate_limit_exceeded",
            "headers": {"retry-after": "3.0"},
        },
    )()

    primary_runnable = MagicMock()
    primary_runnable.invoke.side_effect = err_429

    fb_runnable = MagicMock()
    fb_runnable.invoke.return_value = _DummySchema(status="from-fallback")
    fb_chat = MagicMock()
    fb_chat.with_structured_output.return_value = fb_runnable
    monkeypatch.setattr(llm_module, "get_fallback_chat_model", lambda: fb_chat)

    out = llm_module.invoke_structured(
        primary_runnable,
        messages=[("system", "Sys"), ("human", "Usr")],
        output_schema=_DummySchema,
        stage="review_report",
    )
    assert out.status == "from-fallback"
    assert primary_runnable.invoke.call_count == 2  # initial + 1 retry
    assert fb_runnable.invoke.call_count == 1
    diag = llm_module.get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["fallback_model_used"] == "llama-3.3-70b-versatile"
    assert diag["primary_model_failure_category"] == "rate_limited"
    assert diag["primary_model_status_code"] == 429


# ---------------------------------------------------------------------------
# 4. Repair Estimate Quantity Extraction
# ---------------------------------------------------------------------------


def test_04_repair_estimate_quantity_extraction_and_source_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify explicit quantities in line items or source text are extracted without inferring missing quantities."""
    ev_id = str(uuid4())
    doc_id = str(uuid4())
    evidence = {
        "chunk_id": ev_id,
        "document_id": doc_id,
        "filename": "workshop_estimate.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": (
            "1. Front Bumper Retainer Clips | Qty: 4 | Unit Price: INR 250.00 | Net: INR 1,000.00\n"
            "2. Headlamp Bracket Assembly | 2 pcs | Unit Price: INR 1,500.00 | Net: INR 3,000.00"
        ),
    }

    extraction = RepairEstimateExtraction(
        line_items=[
            # LLM omitted quantity on line 1 even though 'Qty: 4' is in source text
            RepairEstimateExtractedLineItem(
                description="Front Bumper Retainer Clips",
                quantity=None,
                unit_price="INR 250.00",
                reported_amount="INR 1,000.00",
                source_evidence_ids=[ev_id],
            ),
            # LLM extracted '2 pcs' with unit label on line 2
            RepairEstimateExtractedLineItem(
                description="Headlamp Bracket Assembly",
                quantity="2 pcs",
                unit_price="INR 1,500.00",
                reported_amount="INR 3,000.00",
                source_evidence_ids=[ev_id],
            ),
        ],
        clarification_needs=[],
        missing_information=[],
        extraction_complete=True,
    )
    structured = MagicMock()
    structured.invoke.return_value = extraction
    chat = MagicMock()
    chat.with_structured_output.return_value = structured
    monkeypatch.setattr(estimate_analyst_module, "get_chat_model", lambda: chat)

    result = analyze_repair_estimate(
        task="Analyze repair estimate.",
        estimate_evidence=[evidence],
        source_data_complete=True,
    )

    assert result.estimate_status == "complete"
    assert result.line_items[0].quantity == "4"
    assert result.line_items[0].normalized_quantity == 4
    assert result.line_items[0].normalized_unit_price == Decimal("250.00")
    assert result.line_calculations[0].calculated_total == Decimal("1000.00")
    assert result.line_items[1].normalized_quantity == 2
    assert result.line_calculations[1].calculated_total == Decimal("3000.00")
    assert result.complete_estimate_total == Decimal("4000.00")


# ---------------------------------------------------------------------------
# 5. Missing Quantities and Invalid Calculations
# ---------------------------------------------------------------------------


def test_05_missing_quantities_retain_unit_and_reported_amounts_without_fabricating_calculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When source has unit price and reported amount but no quantity, retain both and flag quantity as unavailable."""
    ev_id = str(uuid4())
    doc_id = str(uuid4())
    evidence = {
        "chunk_id": ev_id,
        "document_id": doc_id,
        "filename": "motor_claim_repair_estimate.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": (
            "1. Front Bumper Cover (Material: Plastic):\n"
            "   Gross Part Price: INR 8,500.00 | Depreciation (50%): INR 4,250.00 | Net: INR 4,250.00"
        ),
    }

    extraction = RepairEstimateExtraction(
        line_items=[
            RepairEstimateExtractedLineItem(
                description="Front Bumper Cover (Material: Plastic)",
                quantity=None,
                unit_price="INR 8,500.00",
                reported_amount="INR 4,250.00",
                source_evidence_ids=[ev_id],
            )
        ],
        clarification_needs=[],
        missing_information=[],
        extraction_complete=True,
    )
    structured = MagicMock()
    structured.invoke.return_value = extraction
    chat = MagicMock()
    chat.with_structured_output.return_value = structured
    monkeypatch.setattr(estimate_analyst_module, "get_chat_model", lambda: chat)

    result = analyze_repair_estimate(
        task="Analyze repair estimate.",
        estimate_evidence=[evidence],
        source_data_complete=True,
    )

    assert result.estimate_status == "incomplete"
    assert result.calculation_complete is False
    assert result.complete_estimate_total is None
    item = result.line_items[0]
    assert item.quantity is None
    assert item.normalized_quantity is None
    assert item.quantity_status == "unavailable"
    assert item.value_status == "reported_only_quantity_unavailable"
    assert item.normalized_unit_price == Decimal("8500.00")
    assert item.normalized_reported_amount == Decimal("4250.00")
    assert item.currency == "INR"
    assert result.line_calculations[0].calculated_total is None
    assert result.line_calculations[0].valid is False
    codes = {f.code for f in result.findings}
    assert "invalid_quantity" in codes
    assert "invalid_unit_amount" not in codes


# ---------------------------------------------------------------------------
# 6. Parts and Labour Classification
# ---------------------------------------------------------------------------


def test_06_parts_and_labour_classification_and_subtotals() -> None:
    """Verify part vs labor classification and category subtotal computation."""
    assert classify_line_item_category("Front Bumper Cover (Plastic)") == "part"
    assert classify_line_item_category("Left Headlamp Assembly (LED)") == "part"
    assert classify_line_item_category("Bumper Removal, Fitting & Alignment Labor") == "labor"
    assert classify_line_item_category("Surface Preparation, Primer & Paint") == "labor"
    assert classify_line_item_category("Left Fender Blending & Buffing") == "labor"

    calc = calculate_repair_estimate(
        [
            EstimateLineItem(
                description="Front Bumper Cover",
                quantity="1",
                unit_amount="INR 8,500.00",
                reported_amount="INR 4,250.00",
                source_evidence_ids=("ev-1",),
            ),
            EstimateLineItem(
                description="Bumper Removal, Fitting & Alignment Labor",
                quantity="1",
                unit_amount="INR 3,500.00",
                reported_amount="INR 3,500.00",
                source_evidence_ids=("ev-1",),
            ),
        ],
        source_data_complete=True,
    )
    assert calc.parts_subtotal == Decimal("8500.00")
    assert calc.labor_subtotal == Decimal("3500.00")
    assert calc.reported_line_items_subtotal == Decimal("7750.00")


# ---------------------------------------------------------------------------
# 7. Subtotal and Total Reconciliation
# ---------------------------------------------------------------------------


def test_07_subtotal_and_total_reconciliation_detects_net_discrepancy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify reconciliation of parts/labor/net subtotals against printed document totals."""
    ev_id = str(uuid4())
    doc_id = str(uuid4())
    evidence = {
        "chunk_id": ev_id,
        "document_id": doc_id,
        "filename": "repair_estimate.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": (
            "1. Front Bumper Cover: Gross Part Price: INR 8,500.00 | Depreciation (50%): INR 4,250.00 | Net: INR 4,250.00\n"
            "2. Front Bumper Lower Grille & Clips: Gross Part Price: INR 2,200.00 | Depreciation (50%): INR 1,100.00 | Net: INR 1,100.00\n"
            "3. Left Headlamp Assembly: Gross Part Price: INR 7,400.00 | Depreciation (50%): INR 3,700.00 | Net: INR 3,700.00\n"
            "4. Left Front Fender Panel: Gross Part Price: INR 800.00 | Depreciation (20%): INR 160.00 | Net: INR 640.00\n"
            "5. Bumper Removal, Fitting & Alignment Labor: INR 3,500.00\n"
            "6. Surface Preparation, Primer & Paint: INR 8,000.00\n"
            "7. Left Fender Blending & Buffing: INR 2,000.00\n"
            "TOTAL GROSS ESTIMATE: INR 32,400.00\n"
            "Policy Compulsory Deductible to be Deducted upon Settlement: INR 1,000.00\n"
            "Net Admissible Estimate before Tax: INR 22,440.00"
        ),
    }

    extraction = RepairEstimateExtraction(
        line_items=[
            RepairEstimateExtractedLineItem(
                description="Front Bumper Cover",
                quantity=None,
                unit_price="INR 8,500.00",
                reported_amount="INR 4,250.00",
                source_evidence_ids=[ev_id],
            ),
            RepairEstimateExtractedLineItem(
                description="Front Bumper Lower Grille & Clips",
                quantity=None,
                unit_price="INR 2,200.00",
                reported_amount="INR 1,100.00",
                source_evidence_ids=[ev_id],
            ),
            RepairEstimateExtractedLineItem(
                description="Left Headlamp Assembly",
                quantity=None,
                unit_price="INR 7,400.00",
                reported_amount="INR 3,700.00",
                source_evidence_ids=[ev_id],
            ),
            RepairEstimateExtractedLineItem(
                description="Left Front Fender Panel",
                quantity=None,
                unit_price="INR 800.00",
                reported_amount="INR 640.00",
                source_evidence_ids=[ev_id],
            ),
            RepairEstimateExtractedLineItem(
                description="Bumper Removal, Fitting & Alignment Labor",
                quantity=None,
                unit_price="INR 3,500.00",
                reported_amount="INR 3,500.00",
                source_evidence_ids=[ev_id],
            ),
            RepairEstimateExtractedLineItem(
                description="Surface Preparation, Primer & Paint",
                quantity=None,
                unit_price="INR 8,000.00",
                reported_amount="INR 8,000.00",
                source_evidence_ids=[ev_id],
            ),
            RepairEstimateExtractedLineItem(
                description="Left Fender Blending & Buffing",
                quantity=None,
                unit_price="INR 2,000.00",
                reported_amount="INR 2,000.00",
                source_evidence_ids=[ev_id],
            ),
        ],
        clarification_needs=[],
        missing_information=[],
        extraction_complete=True,
    )
    structured = MagicMock()
    structured.invoke.return_value = extraction
    chat = MagicMock()
    chat.with_structured_output.return_value = structured
    monkeypatch.setattr(estimate_analyst_module, "get_chat_model", lambda: chat)

    result = analyze_repair_estimate(
        task="Analyze repair estimate.",
        estimate_evidence=[evidence],
        source_data_complete=True,
    )

    assert result.parts_subtotal == Decimal("18900.00")
    assert result.labor_subtotal == Decimal("13500.00")
    assert result.reported_line_items_subtotal == Decimal("23190.00")
    assert result.reported_gross_total == Decimal("32400.00")
    assert result.reported_depreciation_total == Decimal("9210.00")
    assert result.reported_deductible == Decimal("1000.00")
    assert result.reported_net_total == Decimal("22440.00")
    # 23190 - 1000 = 22190 != 22440 -> reconciliation mismatch flagged!
    assert result.subtotal_reconciled is False
    assert any(
        f.code == "subtotal_reconciliation_mismatch" for f in result.findings
    )


# ---------------------------------------------------------------------------
# 8. Missing Information Found in Another Document
# ---------------------------------------------------------------------------


def test_08_missing_information_reconciled_when_found_in_another_document() -> None:
    """Verify a specialist's missing-info claim is reconciled and removed when another source provides it."""
    rc_ev = ReviewReportEvidenceChunk(
        chunk_id="ev-rc-1",
        document_id=str(uuid4()),
        filename="vehicle_rc_and_dl.pdf",
        page_number=1,
        chunk_index=0,
        text="Vehicle Registration Number: MH-12-AB-1234. Driving Licence No: MH12-20190012345 (Valid).",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[rc_ev],
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "summary": "Intake complete.",
                "extracted_fields": [],
                "document_flags": [],
                "document_inventory": [],
                "missing_information": [
                    "Driving licence and registration certificate (RC/DL) were not provided."
                ],
                "overall_assessment": "documents_incomplete",
                "human_review_required": True,
            },
        ),
        evidence_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    fallback = build_fallback_partial_report(
        report_input=report_input,
        error_message="synthetic_fallback",
    )
    assert not any(
        "driving licence" in m.statement.casefold() for m in fallback.missing_information
    )
    rec = next(
        r
        for r in fallback.missing_information_reconciliation
        if "driving licence" in r.original_statement.casefold()
    )
    assert rec.reconciled_category == "retrieved_unverified"
    assert rec.retained_in_missing_information is False
    assert "vehicle_rc_and_dl.pdf" in rec.available_in_sources


# ---------------------------------------------------------------------------
# 9. Retrieved But Unverified Policy Clauses
# ---------------------------------------------------------------------------


def test_09_retrieved_but_unverified_policy_clauses_marked_pending_review() -> None:
    """Verify pending_review policy clauses are never treated as verified or missing."""
    pol_ev = ReviewReportEvidenceChunk(
        chunk_id="ev-pol-1",
        document_id=str(uuid4()),
        filename="motor_policy_v1.pdf",
        page_number=1,
        chunk_index=0,
        text="1. Policy Schedule: Insured Declared Value (IDV): INR 800,000.",
        clause_identifier="1",
        verification_status="pending_review",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[pol_ev],
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
        evidence_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis=PolicyAnalystOutput(
                summary="Policy schedule reviewed.",
                relevant_clauses=[
                    PolicyClauseFinding(
                        finding="Insured Declared Value (IDV): INR 800,000.",
                        supporting_evidence_ids=["ev-pol-1"],
                        supporting_quotes=[
                            PolicyEvidenceQuote(
                                evidence_id="ev-pol-1",
                                quote="Insured Declared Value (IDV): INR 800,000.",
                            )
                        ],
                        explanation="Schedule IDV.",
                        confidence="high",
                    )
                ],
                missing_information=["Policy schedule copy is missing."],
                overall_assessment="potentially_supportive",
                human_review_required=True,
            ).model_dump(mode="json"),
        ),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    report = build_fallback_partial_report(
        report_input=report_input,
        error_message="test",
    )
    assert report.policy_verification_status == "pending_review"
    assert any(
        r.reconciled_category == "retrieved_unverified"
        for r in report.missing_information_reconciliation
    )
    assert any("pending_review" in w for w in report.validation_warnings)


# ---------------------------------------------------------------------------
# 10 & 11. Specialist-Specific Document Retrieval & Photograph/Estimate Inventory
# ---------------------------------------------------------------------------


def test_10_and_11_specialist_retrieved_estimate_and_photograph_source_inventory() -> None:
    """Verify specialist-retrieved repair estimate, damage photographs, and uploaded_not_retrieved docs in source_inventory."""
    est_doc_id = str(uuid4())
    photo_doc_id = str(uuid4())
    unret_doc_id = str(uuid4())

    est_ev = ReviewReportEvidenceChunk(
        chunk_id="ev-est-1",
        document_id=est_doc_id,
        filename="motor_claim1_repair_estimate.pdf",
        page_number=1,
        chunk_index=0,
        text="1. Front Bumper Cover: Gross Part Price: INR 8,500.00",
    )
    photo_ev = ReviewReportEvidenceChunk(
        chunk_id="ev-photo-1",
        document_id=photo_doc_id,
        filename="motor_claim1_damage_photos.pdf",
        page_number=1,
        chunk_index=0,
        text="Visual inspection photograph shows front bumper impact and left headlamp crack.",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[est_ev, photo_ev],
        evidence_retrieval_status="completed",
        specialist_evidence_usage={
            "repair_estimate_channel": ["ev-est-1"],
            "repair_estimate_analyst": ["ev-est-1"],
        },
        uploaded_documents=[
            {
                "document_id": est_doc_id,
                "filename": "motor_claim1_repair_estimate.pdf",
                "processing_status": "processed",
            },
            {
                "document_id": photo_doc_id,
                "filename": "motor_claim1_damage_photos.pdf",
                "processing_status": "processed",
            },
            {
                "document_id": unret_doc_id,
                "filename": "spot_survey_annexure.pdf",
                "processing_status": "uploaded",
            },
        ],
        intake_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
        evidence_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis=EvidenceAnalystOutput(
                summary="Photos reviewed.",
                factual_findings=[
                    ClaimEvidenceFinding(
                        finding="Visual inspection photograph shows front bumper impact.",
                        supporting_evidence_ids=["ev-photo-1"],
                        explanation="From damage photos.",
                        confidence="high",
                    )
                ],
                overall_assessment="supportive",
                human_review_required=True,
            ).model_dump(mode="json"),
        ),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "estimate_status": "incomplete",
                "line_items": [
                    {
                        "description": "Front Bumper Cover",
                        "quantity": None,
                        "unit_price": "INR 8,500.00",
                        "reported_amount": "INR 4,250.00",
                        "source_evidence_ids": ["ev-est-1"],
                        "sources": [
                            {
                                "evidence_id": "ev-est-1",
                                "document_id": est_doc_id,
                                "filename": "motor_claim1_repair_estimate.pdf",
                                "page_number": 1,
                            }
                        ],
                    }
                ],
                "line_calculations": [
                    {"line_item_index": 0, "calculated_total": None, "valid": False}
                ],
                "findings": [],
                "clarification_needs": [],
                "missing_information": [],
                "valid_line_subtotal": "0.00",
                "complete_estimate_total": None,
                "source_data_complete": True,
                "calculation_complete": False,
                "human_review_required": True,
            },
        ),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    report = build_fallback_partial_report(
        report_input=report_input,
        error_message="test",
    )
    inv_by_id = {item.document_id: item for item in report.source_inventory}
    assert len(inv_by_id) == 3

    est_inv = inv_by_id[est_doc_id]
    assert est_inv.document_type == "repair_estimate"
    assert est_inv.retrieval_status == "specialist_retrieved"
    assert "repair_estimate_analyst" in est_inv.used_by_specialists

    photo_inv = inv_by_id[photo_doc_id]
    assert photo_inv.document_type == "damage_photographs"
    assert photo_inv.retrieval_status == "retrieved"
    assert "evidence_analyst" in photo_inv.used_by_specialists

    unret_inv = inv_by_id[unret_doc_id]
    assert unret_inv.retrieval_status == "uploaded_not_retrieved"
    assert unret_inv.used_by_specialists == []


# ---------------------------------------------------------------------------
# 12. Duplicate Source Prevention & Duplicate Line-Item Detection
# ---------------------------------------------------------------------------


def test_12_duplicate_source_prevention_and_duplicate_line_items_without_quantity() -> None:
    """Verify multi-chunk documents are deduplicated in source_inventory and duplicate line items without quantity are flagged."""
    shared_doc_id = str(uuid4())
    c1 = ReviewReportEvidenceChunk(
        chunk_id="c-1",
        document_id=shared_doc_id,
        filename="itemized_bill.pdf",
        page_number=1,
        chunk_index=0,
        text="Page 1 billing summary.",
    )
    c2 = ReviewReportEvidenceChunk(
        chunk_id="c-2",
        document_id=shared_doc_id,
        filename="itemized_bill.pdf",
        page_number=2,
        chunk_index=1,
        text="Page 2 billing details.",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health", "status": "under_review"},
        retrieved_evidence=[c1, c2],
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
        evidence_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )
    report = build_fallback_partial_report(
        report_input=report_input,
        error_message="test",
    )
    assert len(report.source_inventory) == 1
    assert report.source_inventory[0].document_id == shared_doc_id
    assert report.source_inventory[0].evidence_ids == ["c-1", "c-2"]
    assert report.source_inventory[0].page_numbers == [1, 2]

    # Also verify duplicate repair line items are flagged even when quantity is None
    calc = calculate_repair_estimate(
        [
            EstimateLineItem(
                description="Left Fender Blending & Buffing",
                quantity=None,
                unit_amount="INR 2,000.00",
                source_evidence_ids=("ev-1",),
            ),
            EstimateLineItem(
                description="Left Fender Blending & Buffing",
                quantity=None,
                unit_amount="INR 2,000.00",
                source_evidence_ids=("ev-2",),
            ),
        ],
        source_data_complete=True,
    )
    dup = next(f for f in calc.findings if f.code == "duplicate_line_items")
    assert dup.line_item_indexes == (0, 1)
    assert dup.source_evidence_ids == ("ev-1", "ev-2")


# ---------------------------------------------------------------------------
# 13. Conflicting Financial Amounts
# ---------------------------------------------------------------------------


def test_13_conflicting_financial_amounts_preserved_and_flagged() -> None:
    """Verify conflicting financial amounts for the same role are both preserved and surfaced as a conflict."""
    ev_claim = ReviewReportEvidenceChunk(
        chunk_id="ev-c1",
        document_id=str(uuid4()),
        filename="claim_form.pdf",
        page_number=1,
        chunk_index=0,
        text="Insured Declared Value: INR 650,000 | Compulsory Deductible: INR 1,000",
    )
    ev_policy = ReviewReportEvidenceChunk(
        chunk_id="ev-p1",
        document_id=str(uuid4()),
        filename="policy_schedule.pdf",
        page_number=1,
        chunk_index=0,
        text="Insured declared value (IDV): INR 800,000 | Compulsory Deductible: INR 2,000",
        clause_identifier="1",
        verification_status="pending_review",
    )
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[ev_claim, ev_policy],
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
        evidence_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )
    report = build_fallback_partial_report(
        report_input=report_input,
        error_message="test",
    )
    assert len(report.conflicting_findings) == 2
    conflict_text = " ".join(c.statement for c in report.conflicting_findings)
    assert "INR 650,000" in conflict_text and "INR 800,000" in conflict_text
    assert "INR 1,000" in conflict_text and "INR 2,000" in conflict_text


# ---------------------------------------------------------------------------
# 14, 15, 16, 17. Multi-Claimant Isolation, Health & Motor Domains, and AI/Fallback Validation
# ---------------------------------------------------------------------------


def test_14_15_16_17_multi_claimant_health_and_motor_ai_and_fallback_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify concurrent/sequential health and motor claimant investigations validate cleanly without cross-contamination."""
    # 1. Health Claim Investigation (AI-generated report)
    health_ev = ReviewReportEvidenceChunk(
        chunk_id="health-ev-1",
        document_id=str(uuid4()),
        filename="apollo_discharge_and_bill.pdf",
        page_number=1,
        chunk_index=0,
        text=(
            "Patient Name: Ananya Verma. Admission Date: 2026-02-10. "
            "Discharge Date: 2026-02-14. Final Hospital Bill: INR 92,500."
        ),
    )
    health_input = ReviewReportInput(
        claim_facts={"claim_type": "health", "status": "under_review"},
        retrieved_evidence=[health_ev],
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "summary": "Health intake complete.",
                "extracted_fields": [],
                "document_flags": [],
                "document_inventory": [],
                "missing_information": [
                    "Vehicle repair estimate was not provided."  # Motor-only item -> should be excluded as not_applicable
                ],
                "overall_assessment": "documents_sufficient",
                "human_review_required": True,
            },
        ),
        evidence_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis=EvidenceAnalystOutput(
                summary="Inpatient stay verified.",
                factual_findings=[
                    ClaimEvidenceFinding(
                        finding="Final Hospital Bill: INR 92,500.",
                        supporting_evidence_ids=["health-ev-1"],
                        explanation="Verified on hospital bill.",
                        confidence="high",
                    )
                ],
                overall_assessment="supportive",
                human_review_required=True,
            ).model_dump(mode="json"),
        ),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    structured_health = MagicMock()
    structured_health.invoke.return_value = ReviewReportExtraction(
        observed_facts=[
            ReviewReportItemExtraction(
                statement="Final Hospital Bill: INR 92,500.",
                explanation="Verified in hospital bill.",
                supporting_evidence_ids=["health-ev-1"],
                supporting_quotes=[
                    ReviewReportEvidenceQuote(
                        evidence_id="health-ev-1",
                        quote="Final Hospital Bill: INR 92,500.",
                    )
                ],
                analyst_output_references=[
                    ReviewReportAnalystOutputReference(
                        specialist="evidence_analyst",
                        output_path="/factual_findings/0/finding",
                        finding_text="Final Hospital Bill: INR 92,500.",
                    )
                ],
            )
        ]
    )
    chat_health = MagicMock()
    chat_health.with_structured_output.return_value = structured_health
    monkeypatch.setattr(report_module, "get_chat_model", lambda: chat_health)

    health_report = analyze_review_report(report_input=health_input)
    assert health_report.overall_status == "completed"
    assert health_report.report_completeness == "complete"
    assert health_report.report_validation_status == "validated"
    assert health_report.observed_facts[0].originating_specialist == "evidence_analyst"
    assert any(
        r.reconciled_category == "not_applicable"
        for r in health_report.missing_information_reconciliation
    )

    # 2. Motor Claim Investigation (with repair estimate validation warnings in both AI and fallback reports)
    motor_ev = ReviewReportEvidenceChunk(
        chunk_id="motor-ev-1",
        document_id=str(uuid4()),
        filename="motor_estimate_claim2.pdf",
        page_number=1,
        chunk_index=0,
        text="1. Front Bumper Cover: Gross Part Price: INR 8,500.00 | Net: INR 4,250.00",
    )
    motor_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[motor_ev],
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "summary": "Motor intake complete.",
                "extracted_fields": [],
                "document_flags": [],
                "document_inventory": [],
                "missing_information": [
                    "Hospital discharge summary was not provided."  # Health-only item -> not_applicable
                ],
                "overall_assessment": "documents_sufficient",
                "human_review_required": True,
            },
        ),
        evidence_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "estimate_status": "incomplete",
                "line_items": [
                    {
                        "description": "Front Bumper Cover",
                        "quantity": None,
                        "unit_price": "INR 8,500.00",
                        "reported_amount": "INR 4,250.00",
                        "source_evidence_ids": ["motor-ev-1"],
                        "sources": [
                            {
                                "evidence_id": "motor-ev-1",
                                "document_id": motor_ev.document_id,
                                "filename": "motor_estimate_claim2.pdf",
                                "page_number": 1,
                            }
                        ],
                        "item_category": "part",
                        "normalized_unit_price": "8500.00",
                        "normalized_reported_amount": "4250.00",
                        "quantity_status": "unavailable",
                        "value_status": "reported_only_quantity_unavailable",
                    }
                ],
                "line_calculations": [
                    {"line_item_index": 0, "calculated_total": None, "valid": False}
                ],
                "findings": [
                    {
                        "code": "invalid_quantity",
                        "description": "The line item quantity is missing or unavailable in the source document; unit price and reported amount were retained without fabricating a calculation.",
                        "source_evidence_ids": ["motor-ev-1"],
                        "sources": [
                            {
                                "evidence_id": "motor-ev-1",
                                "document_id": motor_ev.document_id,
                                "filename": "motor_estimate_claim2.pdf",
                                "page_number": 1,
                            }
                        ],
                        "line_item_indexes": [0],
                    }
                ],
                "clarification_needs": [],
                "missing_information": [],
                "valid_line_subtotal": "0.00",
                "complete_estimate_total": None,
                "subtotal_reconciled": False,
                "source_data_complete": True,
                "calculation_complete": False,
                "human_review_required": True,
            },
        ),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    motor_fallback = build_fallback_partial_report(
        report_input=motor_input,
        error_message="rate_limited: RateLimitError",
    )
    assert motor_fallback.report_validation_status == "flagged_for_human_review"
    assert any(
        "invalid_quantity" in w for w in motor_fallback.validation_warnings
    )
    assert any(
        "subtotals do not reconcile" in w for w in motor_fallback.validation_warnings
    )
    assert any(
        r.reconciled_category == "not_applicable"
        for r in motor_fallback.missing_information_reconciliation
    )
    # Ensure zero cross-contamination from the previous health claim
    assert all(
        "apollo_discharge_and_bill.pdf" != s.filename
        for s in motor_fallback.source_inventory
    )


# ---------------------------------------------------------------------------
# 18. Pre-Finalization Shared Evidence Context Reconciliation & Document Status
# ---------------------------------------------------------------------------


def test_18_pre_finalization_shared_evidence_reconciliation_and_document_status() -> None:
    """Verify specialist missing_information is reconciled against the shared evidence context
    before findings are finalized, and document_status accurately reflects retrieved_unverified
    vs verified vs uploaded_not_retrieved.
    """
    from claimsage.agents.report_validation import (
        build_shared_evidence_context,
        reconcile_specialist_missing_in_state,
    )

    rc_chunk = {
        "chunk_id": "chunk-rc-01",
        "document_id": str(uuid4()),
        "filename": "vehicle_rc_and_dl.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": "Registration Number: KA-01-XY-7890. Driving Licence No: KA0120200099887.",
        "extraction_method": "native",
    }
    pol_chunk = {
        "chunk_id": "chunk-pol-01",
        "document_id": str(uuid4()),
        "filename": "motor_policy_schedule.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": "Clause 1: Insured Declared Value (IDV): INR 600,000.",
        "clause_identifier": "1",
        "verification_status": "pending_review",
    }
    est_chunk = {
        "chunk_id": "chunk-est-01",
        "document_id": str(uuid4()),
        "filename": "authorized_repair_estimate.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "text": "1. Rear Bumper Assembly: Qty 1 | Unit Price: INR 12,000.00 | Amount: INR 12,000.00",
    }

    state = {
        "claim_facts": {"claim_type": "auto", "status": "under_review"},
        "claim_evidence": [rc_chunk],
        "policy_evidence": [pol_chunk],
        "repair_estimate_evidence": [est_chunk],
        "intake_analysis": {
            "summary": "Intake review.",
            "missing_information": [
                "Driving licence and registration certificate (RC) were not provided.",
                "Repair estimate document is missing.",
                "Policy schedule copy was not provided.",
                "Hospital discharge summary is missing.",  # Health-only on motor claim -> not_applicable
                "Original final payment receipt was not provided.",  # Genuinely not provided -> retained
            ],
        },
        "intake_analysis_status": "completed",
        "result": {
            "uploaded_documents": [
                {
                    "document_id": "doc-unret-99",
                    "filename": "dashcam_still_frame.pdf",
                    "processing_status": "uploaded",
                }
            ]
        },
    }

    ctx = build_shared_evidence_context(state)
    assert ctx.document_statuses["vehicle_rc_and_dl.pdf"] == "retrieved_unverified"
    assert ctx.document_statuses["motor_policy_schedule.pdf"] == "retrieved_unverified"
    assert ctx.document_statuses["authorized_repair_estimate.pdf"] == "retrieved_unverified"
    assert ctx.document_statuses["dashcam_still_frame.pdf"] == "uploaded_not_retrieved"

    updates = reconcile_specialist_missing_in_state(state)
    assert "intake_analysis" in updates
    reconciled_intake = updates["intake_analysis"]
    # Only the genuinely missing item remains in specialist missing_information!
    assert reconciled_intake["missing_information"] == [
        "Original final payment receipt was not provided."
    ]
    shared_rec = updates["result"]["shared_evidence_reconciliation"]
    assert len(shared_rec) == 4
    categories = {r["reconciled_category"] for r in shared_rec}
    assert "retrieved_unverified" in categories
    assert "not_applicable" in categories


# ---------------------------------------------------------------------------
# 19. Deterministic Report When Groq Is Completely Unavailable & DB Persistence
# ---------------------------------------------------------------------------


def test_19_deterministic_report_when_groq_completely_unavailable_and_db_persistence() -> None:
    """Verify deterministic report generation when all LLM stages are unavailable,
    and verify _sync_report persists the deterministic fallback report in InvestigationReport.
    """
    from claimsage.agents.review_report_agent import generate_deterministic_report
    from claimsage.services.investigation_persistence import _sync_report

    claim_ev = ReviewReportEvidenceChunk(
        chunk_id="det-claim-1",
        document_id=str(uuid4()),
        filename="incident_and_claim_form.pdf",
        page_number=1,
        chunk_index=0,
        text="Incident Date: 2026-05-10. Insured Declared Value (IDV): INR 450,000.",
    )
    pol_ev = ReviewReportEvidenceChunk(
        chunk_id="det-pol-1",
        document_id=str(uuid4()),
        filename="motor_policy_v1.pdf",
        page_number=1,
        chunk_index=0,
        text="Clause 2.1: Insured Declared Value (IDV): INR 750,000. Compulsory Deductible: INR 2,000.",
        clause_identifier="2.1",
        verification_status="pending_review",
    )
    est_ev = ReviewReportEvidenceChunk(
        chunk_id="det-est-1",
        document_id=str(uuid4()),
        filename="garage_repair_estimate.pdf",
        page_number=1,
        chunk_index=0,
        text=(
            "1. Front Headlamp Assembly: Gross Part Price: INR 14,000.00 | Depreciation (50%): INR 7,000.00 | Net: INR 7,000.00\n"
            "2. Labour Charges - Headlamp R&R: Qty: 1 | Unit Price: INR 1,500.00 | Amount: INR 1,500.00\n"
            "Net Estimate Total: INR 8,500.00"
        ),
    )

    # All 5 LLM specialists failed due to Groq unavailability
    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[claim_ev, pol_ev, est_ev],
        uploaded_documents=[
            {
                "document_id": "up-unret-1",
                "filename": "unindexed_survey_annexure.pdf",
                "processing_status": "failed",
            }
        ],
        specialist_evidence_usage={"repair_estimate_channel": ["det-est-1"]},
        evidence_retrieval_status="completed",
        intake_agent=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        evidence_analyst=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="unavailable", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="unavailable", analysis=None),
    )

    det_report = generate_deterministic_report(
        report_input=report_input,
        error_message="rate_limited: Groq 429 across all stages",
    )

    assert det_report.report_generation_mode == "deterministic_fallback"
    assert det_report.overall_status == "incomplete"
    assert det_report.human_review_required is True
    assert det_report.policy_verification_status == "pending_review"

    # Must include deterministic policy clause finding, repair estimate calculation summary, and IDV conflict
    fact_statements = [f.statement for f in det_report.observed_facts]
    assert any("Clause 2.1" in s or "750,000" in s for s in fact_statements)
    assert any("Repair estimate contains" in s for s in fact_statements)
    assert any(
        "450,000" in c.statement and "750,000" in c.statement
        for c in det_report.conflicting_findings
    )

    # Check source_inventory document_status
    inv_by_name = {i.filename: i for i in det_report.source_inventory}
    assert inv_by_name["garage_repair_estimate.pdf"].document_status == "retrieved_unverified"
    assert inv_by_name["motor_policy_v1.pdf"].document_status == "retrieved_unverified"
    assert inv_by_name["unindexed_survey_annexure.pdf"].document_status == "uploaded_not_retrieved"

    # Verify _sync_report persists fallback_report into InvestigationReport when review_report is None
    mock_session = MagicMock()
    mock_session.scalar.return_value = None
    added_objects: list[object] = []
    mock_session.add.side_effect = lambda obj: added_objects.append(obj)

    inv_run = SimpleNamespace(id=uuid4())
    state_with_fallback = {
        "review_report": None,
        "review_report_status": "unavailable",
        "result": {
            "review_report": None,
            "review_report_status": "unavailable",
            "fallback_report": det_report.model_dump(mode="json"),
            "limitations": ["AI synthesis unavailable; deterministic fallback report generated."],
        },
    }
    _sync_report(mock_session, inv_run, state_with_fallback)
    assert len(added_objects) == 1
    persisted_report = added_objects[0]
    assert getattr(persisted_report, "status") == "incomplete"
    report_data = getattr(persisted_report, "report_data")
    assert isinstance(report_data, dict)
    assert report_data["report_generation_mode"] == "deterministic_fallback"
    assert len(report_data["observed_facts"]) >= 2
    assert len(report_data["conflicting_findings"]) >= 1

