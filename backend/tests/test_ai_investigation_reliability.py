"""Comprehensive regression and reliability test suite for ClaimSage AI investigation.

Verifies the remediation of:
- Failure A: Evidence Analyst HTTP 400 Bad Request (schema compatibility)
- Failure B & C: Policy Analyst & Risk Anomaly HTTP 429 Too Many Requests (bounded retries & backoff)
- Failure D: Review Report Agent HTTP 413 Payload Too Large (context reduction & token budgeting)
- Complete error taxonomy (12 categories) & partial success preservation
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field, SecretStr

from claimsage.agents import llm
from claimsage.agents.evidence_analyst import (
    EvidenceAnalystError,
    analyze_claim_evidence,
)
from claimsage.agents.graph import run_evidence_analyst
from claimsage.agents.review_report_agent import (
    ReviewReportAgentError,
    _build_compact_model_payload,
)
from claimsage.agents.schemas import (
    ClaimEvidenceFinding,
    EvidenceAnalystOutput,
    ReviewReportEvidenceChunk,
    ReviewReportInput,
    ReviewReportSpecialistInput,
)
from claimsage.services.investigation_persistence import is_investigation_complete


class MockSettings:
    """Mock application settings for isolated unit testing."""

    groq_api_key = SecretStr("mock-api-key-test")
    groq_tokenizer_encoding = "o200k_harmony"
    groq_max_input_tokens = 24000
    groq_max_output_tokens = 2048
    groq_timeout_seconds = 10.0
    groq_max_retries = 3
    groq_max_retry_delay_seconds = 15.0
    groq_concurrency_limit = 2
    groq_model = "openai/gpt-oss-120b"


class MockRunnable:
    """Mock runnable that yields predetermined responses or raises exceptions."""

    def __init__(self, sequence: list[object]) -> None:
        self.sequence = list(sequence)
        self.call_count = 0

    def invoke(self, messages: object) -> object:
        if self.call_count >= len(self.sequence):
            raise RuntimeError("Exhausted MockRunnable sequence.")
        result = self.sequence[self.call_count]
        self.call_count += 1
        if isinstance(result, BaseException):
            raise result
        return result


# ---------------------------------------------------------------------------
# Test Failure A: Evidence Analyst Schema Compatibility (HTTP 400 Prevention)
# ---------------------------------------------------------------------------

def test_evidence_analyst_schema_has_no_const_or_unsupported_min_items():
    """Verify JSON Schema generated for function calling omits const and minItems."""
    schema = EvidenceAnalystOutput.model_json_schema()
    
    props = schema.get("properties", {})
    hrr = props.get("human_review_required", {})
    assert "const" not in hrr, "Schema must not emit 'const' keyword for Groq compatibility"
    assert hrr.get("type") == "boolean"
    assert hrr.get("default") is True

    defs = schema.get("$defs", {})
    for model_name, model_def in defs.items():
        for field_name, field_prop in model_def.get("properties", {}).items():
            assert "minItems" not in field_prop, (
                f"Field {model_name}.{field_name} must not emit minItems"
            )


def test_evidence_analyst_validates_citations_and_enforces_human_review(monkeypatch):
    """Verify Evidence Analyst executes cleanly with mocked response."""
    monkeypatch.setattr(llm, "get_settings", lambda: MockSettings())
    monkeypatch.setattr("claimsage.agents.evidence_analyst.get_chat_model", lambda: MagicMock())

    mock_output = EvidenceAnalystOutput(
        summary="Patient was admitted on 12 March 2026.",
        factual_findings=[
            ClaimEvidenceFinding(
                finding="Hospital admission occurred on 12 March 2026.",
                supporting_evidence_ids=["chunk-001"],
                explanation="Stated explicitly in admission note.",
                confidence="high",
            )
        ],
        timeline=[],
        inconsistencies=[],
        missing_information=[],
        evidence_gaps=[],
        overall_assessment="supportive",
        human_review_required=True,
    )

    mock_runnable = MockRunnable([mock_output])
    monkeypatch.setattr(
        "claimsage.agents.evidence_analyst.invoke_structured",
        lambda runnable, messages, output_schema, stage: mock_runnable.invoke(messages),
    )

    result = analyze_claim_evidence(
        task="Verify dates of hospital admission.",
        claim_evidence=[
            {
                "chunk_id": "chunk-001",
                "text": "Patient was admitted on 12 March 2026.",
                "filename": "admission_record.pdf",
            }
        ],
    )

    assert result.overall_assessment == "supportive"
    assert result.human_review_required is True
    assert len(result.factual_findings) == 1
    assert result.factual_findings[0].supporting_evidence_ids == ["chunk-001"]


def test_evidence_analyst_rejects_missing_citations(monkeypatch):
    """Verify that findings without supporting citations are rejected."""
    monkeypatch.setattr(llm, "get_settings", lambda: MockSettings())
    monkeypatch.setattr("claimsage.agents.evidence_analyst.get_chat_model", lambda: MagicMock())

    # Mock output where factual finding has empty citations
    uncited_output = EvidenceAnalystOutput(
        summary="Patient was admitted on 12 March 2026.",
        factual_findings=[
            ClaimEvidenceFinding(
                finding="Hospital admission occurred.",
                supporting_evidence_ids=[],
                explanation="No citation provided.",
                confidence="low",
            )
        ],
        timeline=[],
        inconsistencies=[],
        missing_information=[],
        evidence_gaps=[],
        overall_assessment="supportive",
        human_review_required=True,
    )

    monkeypatch.setattr(
        "claimsage.agents.evidence_analyst.invoke_structured",
        lambda runnable, messages, output_schema, stage: uncited_output,
    )

    with pytest.raises(EvidenceAnalystError, match="without supporting citations"):
        analyze_claim_evidence(
            task="Verify dates.",
            claim_evidence=[{"chunk_id": "chunk-001", "text": "Valid text"}],
        )


# ---------------------------------------------------------------------------
# Test Failure B & C: HTTP 429 Rate Limiting & Bounded Backoff
# ---------------------------------------------------------------------------

def test_http_429_is_retryable_for_transient_limits():
    """Verify HTTP 429 rate limit is retryable."""
    transient_429 = type(
        "RateLimitError",
        (RuntimeError,),
        {"status_code": 429, "code": "rate_limit_exceeded"},
    )()
    assert llm._is_retryable(transient_429) is True


def test_http_429_is_not_retryable_for_quota_exhaustion():
    """Verify HTTP 429 with quota exhaustion is classified as quota_exceeded and not retried."""
    quota_error = type(
        "QuotaError",
        (RuntimeError,),
        {"status_code": 429, "code": "insufficient_quota"},
    )()
    assert llm.provider_failure_category(quota_error) == "quota_exceeded"
    assert llm._is_retryable(quota_error) is False


def test_invoke_structured_retries_transient_429_with_backoff(monkeypatch):
    """Verify invoke_structured retries transient 429 and succeeds on next attempt."""
    monkeypatch.setattr(llm, "get_settings", lambda: MockSettings())
    sleep_calls: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleep_calls.append(s))

    rate_limit_error = type(
        "Transient429",
        (RuntimeError,),
        {"status_code": 429, "code": "rate_limit_exceeded"},
    )()
    expected_output = SimpleNamespace(success=True)
    runnable = MockRunnable([rate_limit_error, rate_limit_error, expected_output])

    class DummySchema(BaseModel):
        msg: str = "ok"

    result = llm.invoke_structured(
        runnable,
        messages=[("human", "Test prompt")],
        output_schema=DummySchema,
        stage="test_rate_limit",
    )

    assert result is expected_output
    assert runnable.call_count == 3
    assert len(sleep_calls) == 2
    assert all(delay > 0 for delay in sleep_calls)


def test_invoke_structured_respects_retry_after_header(monkeypatch):
    """Verify invoke_structured honors retry-after header from provider."""
    monkeypatch.setattr(llm, "get_settings", lambda: MockSettings())
    sleep_calls: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleep_calls.append(s))

    error_with_header = type(
        "RateLimitHeaderError",
        (RuntimeError,),
        {"status_code": 429, "headers": {"retry-after": "2.5"}},
    )()
    expected_output = SimpleNamespace(done=True)
    runnable = MockRunnable([error_with_header, expected_output])

    class DummySchema(BaseModel):
        msg: str = "ok"

    result = llm.invoke_structured(
        runnable,
        messages=[("human", "Test header")],
        output_schema=DummySchema,
        stage="test_header",
    )

    assert result is expected_output
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 2.5


# ---------------------------------------------------------------------------
# Test Failure D: Review Report Agent HTTP 413 & Context Reduction
# ---------------------------------------------------------------------------

def test_http_413_never_maps_to_rate_limited():
    """Verify HTTP 413 maps to payload_too_large even when provider code is rate_limit_exceeded."""
    error_413 = type(
        "PayloadTooLargeError",
        (RuntimeError,),
        {"status_code": 413, "code": "rate_limit_exceeded"},
    )()
    assert llm.provider_failure_category(error_413) == "payload_too_large"
    assert llm._is_retryable(error_413) is False


def test_review_report_compact_payload_reduces_size():
    """Verify _build_compact_model_payload strips non-essential metadata and deduplicates."""
    chunk_1 = ReviewReportEvidenceChunk(
        chunk_id="chunk-001",
        document_id=uuid4(),
        filename="very_long_file_name.pdf",
        page_number=14,
        chunk_index=3,
        text="Essential clinical observation on date of loss.",
        extraction_method="ocr",
        ocr_confidence=98.5,
    )
    chunk_2 = ReviewReportEvidenceChunk(
        chunk_id="chunk-002",
        document_id=uuid4(),
        filename="discharge_summary.pdf",
        page_number=1,
        chunk_index=0,
        text="Discharge instructions and follow-up plan.",
        extraction_method="native",
    )

    report_input = ReviewReportInput(
        claim_facts={"claim_type": "health", "amount": 12000},
        retrieved_evidence=[chunk_1, chunk_2],
        evidence_retrieval_status="completed",
        evidence_retrieval_limitations=[],
        intake_agent=ReviewReportSpecialistInput(status="completed", analysis={"extracted_fields": []}),
        evidence_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "factual_findings": [
                    {
                        "finding": "Observation noted.",
                        "supporting_evidence_ids": ["chunk-001"],
                    }
                ]
            },
        ),
        policy_analyst=ReviewReportSpecialistInput(
            status="completed",
            analysis={
                "relevant_clauses": [],
                "summary_quotes": [{"evidence_id": "quote-1", "quote": "duplicate quote"}],
                "assessment_quotes": [{"evidence_id": "quote-2", "quote": "duplicate quote 2"}],
            },
        ),
        repair_estimate_analyst=ReviewReportSpecialistInput(status="skipped", analysis=None),
        risk_anomaly_agent=ReviewReportSpecialistInput(status="skipped", analysis=None),
    )

    payload = _build_compact_model_payload(report_input)

    # Check evidence compaction
    assert len(payload["retrieved_evidence"]) == 2
    first_ev = payload["retrieved_evidence"][0]
    assert "chunk_id" in first_ev
    assert "text" in first_ev
    assert "filename" not in first_ev
    assert "ocr_confidence" not in first_ev
    assert "document_id" not in first_ev

    # Check policy analyst pruning of redundant quote arrays
    policy_spec = payload["specialist_analyses"]["policy_analyst"]
    assert "summary_quotes" not in policy_spec["analysis"]
    assert "assessment_quotes" not in policy_spec["analysis"]


# ---------------------------------------------------------------------------
# Test Complete Error Taxonomy (12 Categories)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("error", "expected_category"),
    [
        (type("InvalidReq", (RuntimeError,), {"status_code": 400})(), "invalid_request"),
        (type("AuthErr", (RuntimeError,), {"status_code": 401})(), "authentication_error"),
        (type("PermErr", (RuntimeError,), {"status_code": 403})(), "permission_error"),
        (type("RateLimit", (RuntimeError,), {"status_code": 429})(), "rate_limited"),
        (type("QuotaErr", (RuntimeError,), {"status_code": 429, "code": "quota_exceeded"})(), "quota_exceeded"),
        (type("PayloadTooLarge", (RuntimeError,), {"status_code": 413})(), "payload_too_large"),
        (llm.ModelContextLimitError("exceeded"), "context_length_exceeded"),
        (TimeoutError("request timeout"), "provider_timeout"),
        (type("ServerErr", (RuntimeError,), {"status_code": 503})(), "provider_unavailable"),
        (ConnectionError("conn reset"), "provider_unavailable"),
        (type("MalformedJson", (RuntimeError,), {"name": "OutputParserException"})(), "malformed_response"),
        (RuntimeError("unclassified error"), "unknown_provider_error"),
    ],
)
def test_complete_error_taxonomy(error, expected_category):
    """Verify that every error type correctly maps to the defined 12-category taxonomy."""
    assert llm.provider_failure_category(error) == expected_category


# ---------------------------------------------------------------------------
# Test Partial Success & Safety Invariant Preservation
# ---------------------------------------------------------------------------

def test_workflow_marks_investigation_incomplete_when_report_fails():
    """Verify state with provider failures is classified as incomplete, not completed."""
    state_with_failure = {
        "error": None,
        "result": {
            "review_report_status": "unavailable",
            "provider_failures": [
                {"stage": "review_report", "category": "payload_too_large"}
            ],
            "human_review_required": True,
            "evidence_analysis": {"factual_findings": ["finding-1"]},
        },
    }
    assert is_investigation_complete(state_with_failure) is False


def test_evidence_analyst_failure_preserves_retrieved_evidence_in_state(monkeypatch):
    """Verify when Evidence Analyst model call fails, state marks unavailable but preserves evidence."""
    monkeypatch.setattr(
        "claimsage.agents.graph.analyze_claim_evidence",
        MagicMock(side_effect=EvidenceAnalystError("Model failed")),
    )

    state = {
        "task": "Test task",
        "claim_evidence": [{"chunk_id": "c-1", "text": "Preserved evidence"}],
        "evidence_analysis_status": "pending",
        "result": {"limitations": []},
    }

    update = run_evidence_analyst(state)

    assert update["evidence_analysis_status"] == "unavailable"
    assert update["claim_evidence"] == [{"chunk_id": "c-1", "text": "Preserved evidence"}]
    assert update["evidence_analysis"] is None
    assert any("evidence analysis is temporarily unavailable" in lim for lim in update["result"]["limitations"])
    assert len(update["result"]["provider_failures"]) == 1
    assert update["result"]["provider_failures"][0]["stage"] == "evidence_analysis"


# ---------------------------------------------------------------------------
# Phase 4 Remediation: Rate Limit, Pacing, and Compaction Tests
# ---------------------------------------------------------------------------

def test_retry_after_parsing_various_formats():
    """Verify _retry_after_seconds parses seconds, ms, and compound min/sec."""
    assert llm._retry_after_seconds("15") == 15.0
    assert llm._retry_after_seconds("28.5s") == 28.5
    assert llm._retry_after_seconds("615ms") == 0.615
    assert llm._retry_after_seconds("1m26.4s") == 86.4
    assert llm._retry_after_seconds("2m") == 120.0
    assert llm._retry_after_seconds("") is None
    assert llm._retry_after_seconds("not-a-duration") is None


def test_groq_reset_header_parsing_and_priority():
    """Verify x-ratelimit-reset-tokens is extracted and parsed into metadata."""
    err = type(
        "RateLimitResetErr",
        (RuntimeError,),
        {
            "status_code": 429,
            "headers": {"x-ratelimit-reset-tokens": "28.5s"},
        },
    )()
    meta = llm.safe_retry_metadata(err)
    assert meta.get("retry_after_seconds") == 28.5


def test_bounded_retry_behavior_does_not_prematurely_cap_at_15s(monkeypatch):
    """Verify provider retry delay > 15s is not truncated to 15s."""
    monkeypatch.setattr(llm, "get_settings", lambda: MockSettings())
    err = type(
        "RateLimitResetErr",
        (RuntimeError,),
        {
            "status_code": 429,
            "headers": {"retry-after": "28.5"},
        },
    )()
    delay = llm._retry_delay(err, attempt=0)
    assert delay == 28.5, f"Expected 28.5s delay to be respected, got {delay}"


def test_configurable_concurrency(monkeypatch):
    """Verify get_model_semaphore dynamically reflects configured concurrency limit."""
    class DynamicSettings(MockSettings):
        groq_concurrency_limit: int = 5

    monkeypatch.setattr(llm, "get_settings", lambda: DynamicSettings())
    llm.reset_model_semaphore()
    sem = llm.get_model_semaphore()
    assert sem._value == 5
    llm.reset_model_semaphore()


def test_compact_risk_payload_structure_and_limits():
    """Verify _build_compact_risk_payload caps chunks at 6 and prioritizes cited evidence."""
    from claimsage.agents.risk_anomaly_agent import _build_compact_risk_payload

    # Create 10 dummy evidence records
    records = [
        {
            "chunk_id": f"chunk-{i:03d}",
            "document_id": f"doc-{i:03d}",
            "filename": f"file_{i}.pdf",
            "page_number": 1,
            "text": f"Evidence text for chunk {i}",
        }
        for i in range(10)
    ]
    # Analyst output citing chunk-008 and chunk-009
    analyst_outputs = {
        "evidence_analyst": {
            "factual_findings": [
                {
                    "finding": "Important finding",
                    "supporting_evidence_ids": ["chunk-008", "chunk-009"],
                }
            ]
        }
    }

    payload = _build_compact_risk_payload(
        task="Check inconsistencies",
        claim_facts={"claimant": "Jane Doe"},
        evidence_records=records,
        completed_analyst_outputs=analyst_outputs,
        max_chunks=6,
    )

    ev_list = payload["claim_evidence"]
    assert len(ev_list) == 6
    chunk_ids = [e["evidence_id"] for e in ev_list]
    assert "chunk-008" in chunk_ids
    assert "chunk-009" in chunk_ids
    assert "claimant" in payload["claim_facts"]
    assert "evidence_analyst" in payload["completed_analyst_outputs"]


def test_graph_pacing_delay_logic(monkeypatch):
    """Verify _apply_pacing_delay respects test mode vs non-test mode."""
    from claimsage.agents.graph import _apply_pacing_delay

    sleeps: list[float] = []
    monkeypatch.setattr("claimsage.agents.graph.time.sleep", lambda s: sleeps.append(s))

    # Test mode: should NOT sleep
    class TestSettings(MockSettings):
        app_env: str = "test"
        groq_pacing_delay_seconds: float = 6.0

    monkeypatch.setattr("claimsage.agents.graph.get_settings", lambda: TestSettings())
    _apply_pacing_delay("policy_analyst")
    assert len(sleeps) == 0

    # Dev/Prod mode: should sleep
    class ProdSettings(MockSettings):
        app_env: str = "development"
        groq_pacing_delay_seconds: float = 6.0

    monkeypatch.setattr("claimsage.agents.graph.get_settings", lambda: ProdSettings())
    _apply_pacing_delay("policy_analyst")
    assert len(sleeps) == 1
    assert sleeps[0] == 6.0
