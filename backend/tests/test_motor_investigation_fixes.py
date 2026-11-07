"""Regression tests for CLM-DEMO-MOTOR-001 root-cause fixes.

Covers:
1. Repair estimate document auto-resolution for motor claims (and exclusion for health claims).
2. Specialist failure and skip diagnostics in state_snapshot.result.stage_diagnostics.
3. Incomplete report status when all active specialists fail/are unavailable while evidence is retrieved.
4. Deterministic cross-document IDV discrepancy preservation (INR 650,000 vs INR 800,000).
5. Multi-line policy clause heading extraction without auto-verifying clauses.
6. Groq quota handling (non-retryable TPD 429 metadata, pacing skip, and explicit fallback model).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, SecretStr

from claimsage.agents import graph as graph_module
from claimsage.agents import llm as llm_module
from claimsage.agents import review_report_agent as report_module
from claimsage.agents.evidence_analyst import EvidenceAnalystError
from claimsage.agents.intake_agent import IntakeAgentError
from claimsage.agents.policy_analyst import PolicyAnalystError
from claimsage.agents.repair_estimate_analyst import RepairEstimateAnalystError
from claimsage.agents.risk_anomaly_agent import RiskAnomalyAgentError
from claimsage.agents.schemas import (
    ReviewReportEvidenceChunk,
    ReviewReportExtraction,
    ReviewReportInput,
    ReviewReportSpecialistInput,
    SupervisorPlan,
)
from claimsage.agents.supervisor import SupervisorError
from claimsage.rag import evidence_retrieval_service as ers_module
from claimsage.rag.evidence_retrieval_service import (
    resolve_repair_estimate_document_id,
)
from claimsage.services import document_persistence as persistence_module


# ---------------------------------------------------------------------------
# 1. Repair Estimate Auto-Resolution Tests
# ---------------------------------------------------------------------------


def test_resolve_repair_estimate_document_id_prefers_estimate_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = uuid4()
    claim_id = uuid4()
    generic_doc_id = uuid4()
    estimate_doc_id = uuid4()

    monkeypatch.setattr(
        ers_module,
        "get_authorized_claim",
        lambda db, *, employee_id, claim_id: SimpleNamespace(
            id=claim_id,
            claim_type="auto",
        ),
    )

    docs = [
        SimpleNamespace(
            id=generic_doc_id,
            filename="ClaimSage_Synthetic_Motor_Claim_Evidence_CLM-DEMO-MOTOR-001.pdf",
        ),
        SimpleNamespace(
            id=estimate_doc_id,
            filename="motor_claim1_repair_estimate.pdf",
        ),
    ]
    mock_db = MagicMock()
    mock_db.scalars.return_value.all.return_value = docs

    resolved = resolve_repair_estimate_document_id(
        mock_db,
        employee_id=employee_id,
        claim_id=claim_id,
    )
    assert resolved == estimate_doc_id


def test_resolve_repair_estimate_document_id_skips_non_motor_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = uuid4()
    claim_id = uuid4()

    monkeypatch.setattr(
        ers_module,
        "get_authorized_claim",
        lambda db, *, employee_id, claim_id: SimpleNamespace(
            id=claim_id,
            claim_type="health",
        ),
    )
    mock_db = MagicMock()
    resolved = resolve_repair_estimate_document_id(
        mock_db,
        employee_id=employee_id,
        claim_id=claim_id,
    )
    assert resolved is None
    mock_db.scalars.assert_not_called()


def test_graph_investigate_auto_resolves_motor_repair_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee_id = uuid4()
    claim_id = uuid4()
    estimate_doc_id = uuid4()

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        lambda session, *, employee_id, claim_id: {
            "claim_id": str(claim_id),
            "claim_number": "CLM-DEMO-MOTOR-001",
            "claim_type": "auto",
            "policy_identifier": "DEMO-MOTOR-SECURE-2026-V1",
            "status": "under_review",
        },
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        lambda session, *, employee_id, claim_id: False,
    )
    monkeypatch.setattr(
        graph_module,
        "resolve_repair_estimate_document_id",
        lambda db, *, employee_id, claim_id: estimate_doc_id,
    )

    state = {
        "employee_id": str(employee_id),
        "claim_id": str(claim_id),
        "task": "Investigate motor claim and repair estimate.",
        "repair_estimate_document_id": None,
    }
    runtime = SimpleNamespace(context={"session": MagicMock()})
    update = graph_module.investigate(state, runtime)

    assert update["repair_estimate_document_id"] == str(estimate_doc_id)
    assert update["result"]["repair_estimate_document_id"] == str(estimate_doc_id)


# ---------------------------------------------------------------------------
# 2. Specialist Failure & Skip Diagnostics Tests
# ---------------------------------------------------------------------------


def test_specialist_failures_and_skips_record_stage_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticRateLimitError(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"

    rate_err = SyntheticRateLimitError("Rate limit reached")

    def fail_intake(**kwargs):
        llm_module.last_invocation_diagnostic_ctx.set({
            "stage": "intake_agent",
            "estimated_input_tokens": 2631,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.42,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "rate_limited",
            "status_code": 429,
            "provider_code": "rate_limit_exceeded",
            "provider_retry_hint": False,
            "retry_after_seconds": 963.0,
        })
        err = IntakeAgentError("Intake unavailable")
        err.__cause__ = rate_err
        raise err

    def fail_evidence(**kwargs):
        llm_module.last_invocation_diagnostic_ctx.set({
            "stage": "evidence_analyst",
            "estimated_input_tokens": 2681,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.38,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "rate_limited",
            "status_code": 429,
            "provider_code": "rate_limit_exceeded",
            "provider_retry_hint": False,
            "retry_after_seconds": 812.0,
        })
        err = EvidenceAnalystError("Evidence unavailable")
        err.__cause__ = rate_err
        raise err

    def fail_policy(**kwargs):
        llm_module.last_invocation_diagnostic_ctx.set({
            "stage": "policy_analyst",
            "estimated_input_tokens": 3523,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.51,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "rate_limited",
            "status_code": 429,
            "provider_code": "rate_limit_exceeded",
            "provider_retry_hint": False,
            "retry_after_seconds": 1185.0,
        })
        err = PolicyAnalystError("Policy unavailable")
        err.__cause__ = rate_err
        raise err

    def fail_risk(**kwargs):
        llm_module.last_invocation_diagnostic_ctx.set({
            "stage": "risk_anomaly_agent",
            "estimated_input_tokens": 2338,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.35,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "rate_limited",
            "status_code": 429,
            "provider_code": "rate_limit_exceeded",
            "provider_retry_hint": False,
            "retry_after_seconds": 602.0,
        })
        err = RiskAnomalyAgentError("Risk unavailable")
        err.__cause__ = rate_err
        raise err

    def fail_supervisor(**kwargs):
        llm_module.last_invocation_diagnostic_ctx.set({
            "stage": "supervisor",
            "estimated_input_tokens": 1111,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 1.15,
            "retry_attempts": 2,
            "status": "unavailable",
            "category": "rate_limited",
            "status_code": 429,
            "provider_code": "rate_limit_exceeded",
            "provider_retry_hint": False,
            "retry_after_seconds": 460.0,
        })
        err = SupervisorError("Supervisor unavailable")
        err.__cause__ = rate_err
        raise err

    claim_chunk = SimpleNamespace(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="ClaimSage_Synthetic_Motor_Claim_Evidence_CLM-DEMO-MOTOR-001.pdf",
        page_number=1,
        chunk_index=0,
        text="Claim Number: CLM-DEMO-MOTOR-001 | Insured Declared Value: INR 650,000",
        similarity=0.88,
        embedding_model="test-model",
        extraction_method="native",
        ocr_confidence=None,
    )
    policy_chunk = SimpleNamespace(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="ClaimSage_Synthetic_Motor_Insurance_Policy_v1.pdf",
        page_number=1,
        chunk_index=0,
        text="1. Policy Schedule: Insured declared value (IDV): INR 800,000 (illustrative schedule value).",
        similarity=0.84,
        embedding_model="test-model",
        clause_id=uuid4(),
        clause_identifier="1",
        clause_category="other",
        verification_status="pending_review",
        policy_version="v1",
        source_url=None,
        insurer_name="Synthetic General Insurance",
        product_name="Motor Comprehensive",
        effective_from=None,
        effective_to=None,
    )

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        lambda session, *, employee_id, claim_id: {
            "claim_id": str(claim_id),
            "claim_number": "CLM-DEMO-MOTOR-001",
            "claim_type": "auto",
            "policy_identifier": "DEMO-MOTOR-SECURE-2026-V1",
            "status": "under_review",
            "loss_date": "2026-11-01",
        },
    )
    monkeypatch.setattr(
        graph_module,
        "has_applicable_policy_documents",
        lambda session, *, employee_id, claim_id: True,
    )
    monkeypatch.setattr(
        graph_module,
        "search_policy_chunks",
        lambda session, **kwargs: [policy_chunk],
    )
    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        lambda session, **kwargs: [claim_chunk],
    )
    monkeypatch.setattr(
        graph_module,
        "resolve_repair_estimate_document_id",
        lambda db, **kwargs: None,
    )
    monkeypatch.setattr(graph_module, "create_supervisor_plan", fail_supervisor)
    monkeypatch.setattr(graph_module, "analyze_claim_documents", fail_intake)
    monkeypatch.setattr(graph_module, "analyze_claim_evidence", fail_evidence)
    monkeypatch.setattr(graph_module, "analyze_policy", fail_policy)
    monkeypatch.setattr(graph_module, "analyze_risk_and_anomalies", fail_risk)

    output = graph_module.run_investigation(
        session=MagicMock(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Investigate motor claim CLM-DEMO-MOTOR-001.",
    )

    diagnostics = output["result"]["stage_diagnostics"]
    assert diagnostics["supervisor"]["status"] == "fallback"
    assert diagnostics["supervisor"]["status_code"] == 429
    assert diagnostics["intake_analysis"]["status"] == "unavailable"
    assert diagnostics["intake_analysis"]["estimated_input_tokens"] == 2631
    assert diagnostics["intake_analysis"]["status_code"] == 429
    assert diagnostics["intake_analysis"]["provider_retry_hint"] is False
    assert diagnostics["evidence_analysis"]["status"] == "unavailable"
    assert diagnostics["evidence_analysis"]["estimated_input_tokens"] == 2681
    assert diagnostics["policy_analysis"]["status"] == "unavailable"
    assert diagnostics["policy_analysis"]["estimated_input_tokens"] == 3523
    assert diagnostics["repair_estimate_analysis"]["status"] == "skipped"
    assert diagnostics["risk_analysis"]["status"] == "unavailable"
    assert diagnostics["risk_analysis"]["estimated_input_tokens"] == 2338

    # Also verify Fix 3 & Fix 4 integration: report is incomplete and preserves IDV discrepancy
    assert output["review_report_status"] == "incomplete"
    assert output["result"]["review_report_status"] == "incomplete"
    report = output["review_report"]
    assert report is not None
    assert report.overall_status == "incomplete"
    assert len(report.conflicting_findings) == 1
    assert "INR 650,000" in report.conflicting_findings[0].statement
    assert "INR 800,000" in report.conflicting_findings[0].statement


# ---------------------------------------------------------------------------
# 3 & 4. Incomplete Report Status & Deterministic IDV Discrepancy Preservation
# ---------------------------------------------------------------------------


def test_review_report_preserves_idv_discrepancy_and_marks_incomplete_when_specialists_unavailable() -> None:
    claim_ev = ReviewReportEvidenceChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        filename="ClaimSage_Synthetic_Motor_Claim_Evidence_CLM-DEMO-MOTOR-001.pdf",
        page_number=1,
        chunk_index=0,
        text=(
            "Policy Number: DEMO-MOTOR-SECURE-2026-V1 | "
            "Insured Declared Value: INR 650,000 | Compulsory Deductible: INR 1,000"
        ),
        extraction_method="native",
    )
    policy_ev = ReviewReportEvidenceChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        filename="ClaimSage_Synthetic_Motor_Insurance_Policy_v1.pdf",
        page_number=1,
        chunk_index=0,
        text=(
            "1. Policy Schedule: Policy Number: DEMO-MOTOR-SECURE-2026-V1 | "
            "Insured declared value (IDV): INR 800,000 (illustrative schedule value)."
        ),
        extraction_method="native",
        clause_identifier="1",
        verification_status="pending_review",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[claim_ev, policy_ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(
            status="unavailable",
            analysis=None,
            limitations=["The specialist analysis was unavailable and is not included."],
        ),
        evidence_analyst=ReviewReportSpecialistInput(
            status="unavailable",
            analysis=None,
            limitations=["The specialist analysis was unavailable and is not included."],
        ),
        policy_analyst=ReviewReportSpecialistInput(
            status="unavailable",
            analysis=None,
            limitations=["The specialist analysis was unavailable and is not included."],
        ),
        repair_estimate_analyst=ReviewReportSpecialistInput(
            status="skipped",
            analysis=None,
            limitations=["The specialist was skipped and did not provide an analysis."],
        ),
        risk_anomaly_agent=ReviewReportSpecialistInput(
            status="unavailable",
            analysis=None,
            limitations=["The specialist analysis was unavailable and is not included."],
        ),
    )

    report = report_module.analyze_review_report(report_input=report_input)

    assert report.overall_status == "incomplete"
    assert report.human_review_required is True
    assert len(report.observed_facts) >= 2
    observed_statements = [item.statement for item in report.observed_facts]
    assert "Insured Declared Value: INR 650,000" in observed_statements
    assert "Insured declared value (IDV): INR 800,000" in observed_statements

    assert len(report.conflicting_findings) == 1
    conflict = report.conflicting_findings[0]
    assert "INR 650,000" in conflict.statement
    assert "INR 800,000" in conflict.statement
    assert len(conflict.conflicting_assertions) == 2
    values = {a.value for a in conflict.conflicting_assertions}
    assert values == {"INR 650,000", "INR 800,000"}
    assert len(report.missing_information) >= 1


def test_review_report_preserves_idv_discrepancy_when_specialists_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_ev = ReviewReportEvidenceChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        filename="ClaimSage_Synthetic_Motor_Claim_Evidence_CLM-DEMO-MOTOR-001.pdf",
        page_number=1,
        chunk_index=0,
        text="Insured Declared Value: INR 650,000",
        extraction_method="native",
    )
    policy_ev = ReviewReportEvidenceChunk(
        chunk_id=str(uuid4()),
        document_id=str(uuid4()),
        filename="ClaimSage_Synthetic_Motor_Insurance_Policy_v1.pdf",
        page_number=1,
        chunk_index=0,
        text="Insured declared value (IDV): INR 800,000",
        extraction_method="native",
        clause_identifier="1",
        verification_status="pending_review",
    )

    structured = MagicMock()
    structured.invoke.return_value = ReviewReportExtraction()
    chat_model = MagicMock()
    chat_model.with_structured_output.return_value = structured
    monkeypatch.setattr(report_module, "get_chat_model", lambda: chat_model)

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "auto", "status": "under_review"},
        retrieved_evidence=[claim_ev, policy_ev],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(
            status="completed",
            analysis={"extracted_fields": []},
        ),
        evidence_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        policy_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    report = report_module.analyze_review_report(report_input=report_input)
    assert report.overall_status == "completed"
    assert len(report.conflicting_findings) == 1
    assert "INR 650,000" in report.conflicting_findings[0].statement
    assert "INR 800,000" in report.conflicting_findings[0].statement


# ---------------------------------------------------------------------------
# 5. Multi-Line Policy Clause Heading Extraction Tests
# ---------------------------------------------------------------------------


def test_multiline_clause_metadata_extraction_skips_running_headers() -> None:
    chunk_page1 = (
        "CLAIMSAGE | SYNTHETIC DEMONSTRATION POLICY\n"
        "Motor Comprehensive Insurance Policy Wording (Synthetic v1)\n"
        "2. Own Damage Coverage\n"
        "The insurer will indemnify the insured against accidental external damage."
    )
    cat1, title1, ident1 = persistence_module._extract_clause_metadata(
        chunk_page1,
        page_number=1,
        chunk_index=0,
    )
    assert ident1 == "2"
    assert cat1 == "coverage"
    assert title1 == "Own Damage Coverage"

    chunk_page2 = (
        "CLAIMSAGE | SYNTHETIC DEMONSTRATION POLICY\n"
        "5. Exclusions\n"
        "Consequential loss, mechanical or electrical breakdown are excluded."
    )
    cat2, title2, ident2 = persistence_module._extract_clause_metadata(
        chunk_page2,
        page_number=2,
        chunk_index=0,
    )
    assert ident2 == "5"
    assert cat2 == "exclusion"
    assert title2 == "Exclusions"

    chunk_schedule = (
        "CLAIMSAGE | SYNTHETIC DEMONSTRATION POLICY\n"
        "1. Policy Schedule\n"
        "Policy Number: DEMO-MOTOR-SECURE-2026-V1"
    )
    cat3, title3, ident3 = persistence_module._extract_clause_metadata(
        chunk_schedule,
        page_number=1,
        chunk_index=0,
    )
    assert ident3 == "1"
    assert cat3 == "other"
    assert title3 == "Policy Schedule"


# ---------------------------------------------------------------------------
# 6. Groq Quota Handling & Explicit Fallback Model Tests
# ---------------------------------------------------------------------------


class _DummyOutput(BaseModel):
    value: str


def test_groq_tpd_quota_exhaustion_is_non_retryable_and_uses_fallback_only_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticTPDError(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"
        headers = {
            "x-should-retry": "false",
            "retry-after": "1185",
        }

    primary_runnable = MagicMock()
    primary_runnable.invoke.side_effect = SyntheticTPDError("TPD limit reached")

    mock_limiter = MagicMock()
    monkeypatch.setattr(llm_module, "get_shared_rate_limiter", lambda: mock_limiter)

    # Case 1: No fallback model configured -> fails immediately on attempt 1 without retry
    settings_no_fb = SimpleNamespace(
        app_env="test",
        groq_api_key=SecretStr("gsk_test_dummy_key_for_unit_tests"),
        groq_model="openai/gpt-oss-120b",
        groq_fallback_model=None,
        llm_temperature=0.0,
        groq_timeout_seconds=30.0,
        groq_max_input_tokens=24000,
        groq_max_output_tokens=1200,
        groq_tokenizer_encoding="o200k_harmony",
        groq_max_retries=3,
        groq_max_retry_delay_seconds=5.0,
        groq_concurrency_limit=2,
        groq_pacing_delay_seconds=0.0,
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings_no_fb)

    with pytest.raises(SyntheticTPDError):
        llm_module.invoke_structured(
            primary_runnable,
            messages=[("system", "Test"), ("human", "Hello")],
            output_schema=_DummyOutput,
            stage="policy_analyst",
        )

    assert primary_runnable.invoke.call_count == 1
    diag = llm_module.get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "unavailable"
    assert diag["category"] == "rate_limited"
    assert diag["status_code"] == 429
    assert diag["provider_code"] == "rate_limit_exceeded"
    assert diag["provider_retry_hint"] is False
    assert diag["retry_after_seconds"] == 1185.0

    # Case 2: Explicitly configured fallback model -> succeeds via fallback and records primary failure metadata
    primary_runnable.reset_mock()
    fallback_structured = MagicMock()
    fallback_structured.invoke.return_value = _DummyOutput(value="fallback-ok")
    fallback_chat = MagicMock()
    fallback_chat.with_structured_output.return_value = fallback_structured

    settings_with_fb = SimpleNamespace(
        **{
            **settings_no_fb.__dict__,
            "groq_fallback_model": "llama-3.3-70b-versatile",
        }
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings_with_fb)
    monkeypatch.setattr(llm_module, "get_fallback_chat_model", lambda: fallback_chat)

    result = llm_module.invoke_structured(
        primary_runnable,
        messages=[("system", "Test"), ("human", "Hello")],
        output_schema=_DummyOutput,
        stage="policy_analyst",
    )

    assert result == _DummyOutput(value="fallback-ok")
    assert primary_runnable.invoke.call_count == 1
    assert fallback_structured.invoke.call_count == 1
    diag_fb = llm_module.get_last_invocation_diagnostic()
    assert diag_fb is not None
    assert diag_fb["status"] == "completed"
    assert diag_fb["fallback_model_used"] == "llama-3.3-70b-versatile"
    assert diag_fb["primary_model_failure_category"] == "rate_limited"
    assert diag_fb["primary_model_status_code"] == 429
    assert diag_fb["primary_model_provider_code"] == "rate_limit_exceeded"


# ---------------------------------------------------------------------------
# 7. Output Token Propagation (4096 Default, No 800-Token Clamp, Bounds Validation)
# ---------------------------------------------------------------------------


def test_output_tokens_default_and_propagation_without_800_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from claimsage.core.config import Settings

    monkeypatch.setenv(
        "JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes-long"
    )
    monkeypatch.delenv("GROQ_MAX_OUTPUT_TOKENS", raising=False)
    default_settings = Settings(_env_file=None)
    assert default_settings.groq_max_output_tokens == 4096

    settings_4096 = SimpleNamespace(
        groq_api_key=SecretStr("gsk_test_dummy_key_for_unit_tests"),
        groq_model="openai/gpt-oss-120b",
        groq_fallback_model="llama-3.3-70b-versatile",
        llm_temperature=0.0,
        groq_timeout_seconds=60.0,
        groq_max_output_tokens=4096,
    )
    constructor = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings_4096)
    monkeypatch.setattr(llm_module, "ChatGroq", constructor)
    llm_module.get_chat_model.cache_clear()
    try:
        llm_module.get_chat_model()
        assert constructor.call_args.kwargs["model"] == "openai/gpt-oss-120b"
        assert constructor.call_args.kwargs["max_tokens"] == 4096

        constructor.reset_mock()
        llm_module.get_fallback_chat_model()
        assert constructor.call_args.kwargs["model"] == "llama-3.3-70b-versatile"
        assert constructor.call_args.kwargs["max_tokens"] == 4096
    finally:
        llm_module.get_chat_model.cache_clear()

    with pytest.raises(ValueError, match="GROQ_MAX_OUTPUT_TOKENS"):
        llm_module._validate_max_output_tokens(64)
    with pytest.raises(ValueError, match="GROQ_MAX_OUTPUT_TOKENS"):
        llm_module._validate_max_output_tokens(16384)


# ---------------------------------------------------------------------------
# 8. Retry Metadata & Cooldown Guard on HTTP 400 vs HTTP 429
# ---------------------------------------------------------------------------


def test_safe_retry_metadata_ignores_ratelimit_reset_headers_on_http_400() -> None:
    err_400 = type(
        "ToolUseFailedErr",
        (RuntimeError,),
        {
            "status_code": 400,
            "code": "tool_use_failed",
            "headers": {
                "x-ratelimit-reset-tokens": "21.022s",
                "x-ratelimit-reset-requests": "29.89s",
            },
        },
    )()
    meta_400 = llm_module.safe_retry_metadata(err_400)
    assert meta_400.get("retry_after_seconds") is None

    err_429 = type(
        "RateLimitErr",
        (RuntimeError,),
        {
            "status_code": 429,
            "code": "rate_limit_exceeded",
            "headers": {
                "x-ratelimit-reset-tokens": "21.022s",
            },
        },
    )()
    meta_429 = llm_module.safe_retry_metadata(err_429)
    assert meta_429.get("retry_after_seconds") == 21.022


# ---------------------------------------------------------------------------
# 9. Explicit Fallback on Repeated tool_use_failed (HTTP 400) & No Cooldown
# ---------------------------------------------------------------------------


def test_repeated_tool_use_failed_uses_explicit_fallback_and_never_invents_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticToolUseFailedError(RuntimeError):
        status_code = 400
        code = "tool_use_failed"
        headers = {
            "x-ratelimit-reset-tokens": "21.022s",
        }

    primary_runnable = MagicMock()
    primary_runnable.invoke.side_effect = SyntheticToolUseFailedError(
        "Failed to parse tool call arguments as JSON"
    )

    mock_limiter = MagicMock()
    monkeypatch.setattr(llm_module, "get_shared_rate_limiter", lambda: mock_limiter)
    monkeypatch.setattr(llm_module.time, "sleep", lambda _s: None)

    settings_no_fb = SimpleNamespace(
        app_env="test",
        groq_api_key=SecretStr("gsk_test_dummy_key_for_unit_tests"),
        groq_model="openai/gpt-oss-120b",
        groq_fallback_model=None,
        llm_temperature=0.0,
        groq_timeout_seconds=30.0,
        groq_max_input_tokens=24000,
        groq_max_output_tokens=4096,
        groq_tokenizer_encoding="o200k_harmony",
        groq_max_retries=2,
        groq_max_retry_delay_seconds=5.0,
        groq_concurrency_limit=2,
        groq_pacing_delay_seconds=0.0,
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings_no_fb)

    # Case 1: No fallback configured -> retries primary (3 attempts), never records 429 cooldown, raises
    with pytest.raises(SyntheticToolUseFailedError):
        llm_module.invoke_structured(
            primary_runnable,
            messages=[("system", "Test"), ("human", "Hello")],
            output_schema=_DummyOutput,
            stage="policy_analyst",
        )

    assert primary_runnable.invoke.call_count == 3
    mock_limiter.record_provider_cooldown.assert_not_called()
    diag = llm_module.get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "unavailable"
    assert diag["category"] == "malformed_response"
    assert diag["status_code"] == 400
    assert diag["provider_code"] == "tool_use_failed"
    assert diag["retry_after_seconds"] is None

    # Case 2: Explicit fallback configured -> invokes fallback after primary attempts and records primary failure diagnostics
    primary_runnable.reset_mock()
    fallback_structured = MagicMock()
    fallback_structured.invoke.return_value = _DummyOutput(value="recovered-by-fallback")
    fallback_chat = MagicMock()
    fallback_chat.with_structured_output.return_value = fallback_structured

    settings_with_fb = SimpleNamespace(
        **{
            **settings_no_fb.__dict__,
            "groq_fallback_model": "llama-3.3-70b-versatile",
        }
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings_with_fb)
    monkeypatch.setattr(llm_module, "get_fallback_chat_model", lambda: fallback_chat)

    result = llm_module.invoke_structured(
        primary_runnable,
        messages=[("system", "Test"), ("human", "Hello")],
        output_schema=_DummyOutput,
        stage="policy_analyst",
    )

    assert result == _DummyOutput(value="recovered-by-fallback")
    assert primary_runnable.invoke.call_count == 3
    assert fallback_structured.invoke.call_count == 1
    mock_limiter.record_provider_cooldown.assert_not_called()
    diag_fb = llm_module.get_last_invocation_diagnostic()
    assert diag_fb is not None
    assert diag_fb["status"] == "completed"
    assert diag_fb["fallback_model_used"] == "llama-3.3-70b-versatile"
    assert diag_fb["primary_model_failure_category"] == "malformed_response"
    assert diag_fb["primary_model_status_code"] == 400
    assert diag_fb["primary_model_provider_code"] == "tool_use_failed"


# ---------------------------------------------------------------------------
# 10. policy_analysis_status Persistence in assemble_result and Graph Nodes
# ---------------------------------------------------------------------------


def test_assemble_result_and_policy_analyst_persist_policy_analysis_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state: dict[str, Any] = {
        "employee_id": str(uuid4()),
        "claim_id": str(uuid4()),
        "task": "Verify policy coverage and exclusions.",
        "claim_facts": {"claim_type": "auto", "status": "under_review"},
        "policy_evidence": [
            {
                "chunk_id": str(uuid4()),
                "document_id": str(uuid4()),
                "filename": "ClaimSage_Synthetic_Motor_Insurance_Policy_v1.pdf",
                "page_number": 1,
                "chunk_index": 0,
                "text": "1. Policy Schedule: IDV INR 800,000.",
            }
        ],
        "policy_retrieval_status": "completed",
        "policy_analysis": None,
        "policy_analysis_status": "pending",
        "ai_analysis_status": "pending",
        "claim_evidence": [],
        "evidence_analysis": None,
        "result": {
            "task": "Verify policy coverage and exclusions.",
            "limitations": [],
        },
    }
    assembled = graph_module.assemble_result(
        state,
        {
            **state["result"],
            "ai_analysis_status": "completed",
        },
    )
    assert assembled["policy_analysis_status"] == "completed"
    assert assembled["ai_analysis_status"] == "completed"

    monkeypatch.setattr(graph_module, "_apply_pacing_delay", lambda _s: None)

    def _fail_policy(**_kwargs: Any) -> Any:
        raise PolicyAnalystError("The Policy Analyst could not complete the model request.")

    monkeypatch.setattr(graph_module, "analyze_policy", _fail_policy)
    out = graph_module.run_policy_analyst(state)  # type: ignore[arg-type]
    assert out["policy_analysis_status"] == "unavailable"
    assert out["ai_analysis_status"] == "unavailable"
    assert out["result"]["policy_analysis_status"] == "unavailable"
    assert out["result"]["ai_analysis_status"] == "unavailable"

