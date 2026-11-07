from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, SecretStr

from claimsage.agents import llm
from claimsage.agents.llm import (
    provider_failure_category,
    safe_provider_error_metadata,
)


def test_safe_provider_error_metadata_reads_status_and_code_attributes() -> None:
    class SyntheticProviderError(RuntimeError):
        status_code = 400
        code = "invalid_request_error"

    assert safe_provider_error_metadata(SyntheticProviderError()) == (
        400,
        "invalid_request_error",
    )


def test_safe_provider_error_metadata_reads_nested_error_body() -> None:
    class SyntheticProviderError(RuntimeError):
        status_code = 401
        body = {
            "error": {
                "code": "invalid_api_key",
                "message": "sensitive provider message",
            }
        }

    assert safe_provider_error_metadata(SyntheticProviderError()) == (
        401,
        "invalid_api_key",
    )


def test_safe_provider_error_metadata_rejects_unbounded_code_values() -> None:
    class SyntheticProviderError(RuntimeError):
        code = "sensitive provider response body"

    assert safe_provider_error_metadata(SyntheticProviderError()) == (None, None)


def test_safe_provider_error_metadata_traverses_wrapped_errors() -> None:
    class SyntheticProviderError(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"

    wrapped_error = RuntimeError("safe wrapper")
    wrapped_error.__cause__ = SyntheticProviderError("provider response")

    assert safe_provider_error_metadata(wrapped_error) == (
        429,
        "rate_limit_exceeded",
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            type("UnauthorizedError", (RuntimeError,), {"status_code": 401})(),
            "authentication_error",
        ),
        (
            type("ForbiddenError", (RuntimeError,), {"status_code": 403})(),
            "permission_error",
        ),
        (
            type("RateLimitError", (RuntimeError,), {"status_code": 429})(),
            "rate_limited",
        ),
        (
            type("QuotaError", (RuntimeError,), {"status_code": 429, "code": "insufficient_quota"})(),
            "quota_exceeded",
        ),
        (
            type("RequestTooLargeError", (RuntimeError,), {"status_code": 413})(),
            "payload_too_large",
        ),
        (
            type("InvalidRequestError", (RuntimeError,), {"status_code": 400})(),
            "invalid_request",
        ),
        (
            type("UnavailableError", (RuntimeError,), {"status_code": 503})(),
            "provider_unavailable",
        ),
        (TimeoutError("synthetic timeout"), "provider_timeout"),
        (ConnectionError("synthetic network failure"), "provider_unavailable"),
        (type("MalformedResponseError", (RuntimeError,), {})(), "malformed_response"),
        (llm.ModelContextLimitError("budget exceeded"), "context_length_exceeded"),
    ],
)
def test_provider_failures_have_safe_categories(
    error: BaseException,
    expected: str,
) -> None:
    assert provider_failure_category(error) == expected


def test_chat_model_uses_configured_timeout_and_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        groq_api_key=SecretStr("synthetic-not-a-real-key"),
        groq_model="synthetic-model",
        llm_temperature=0.0,
        groq_timeout_seconds=17.0,
        groq_max_output_tokens=2048,
    )
    constructor = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "ChatGroq", constructor)
    llm.get_chat_model.cache_clear()
    try:
        llm.get_chat_model()
    finally:
        llm.get_chat_model.cache_clear()

    assert constructor.call_args.kwargs["timeout"] == 17.0
    assert constructor.call_args.kwargs["max_retries"] == 0
    assert constructor.call_args.kwargs["max_tokens"] == 2048
    assert constructor.call_args.kwargs["api_key"] == "synthetic-not-a-real-key"


def _settings(*, max_input_tokens: int = 24000):
    return SimpleNamespace(
        groq_tokenizer_encoding="o200k_harmony",
        groq_max_input_tokens=max_input_tokens,
        groq_timeout_seconds=1.0,
    )


class SyntheticSchema(BaseModel):
    value: str


class SyntheticRunnable:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def invoke(self, _input: object) -> object:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_structured_invocation_retries_bounded_transient_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "get_settings", lambda: _settings())
    monkeypatch.setattr(llm.time, "sleep", lambda _seconds: None)
    result = object()
    runnable = SyntheticRunnable(
        [
            type("TransientError", (RuntimeError,), {"status_code": 503})(),
            result,
        ]
    )

    assert llm.invoke_structured(
        runnable,
        messages=[("human", "Synthetic request.")],
        output_schema=SyntheticSchema,
        stage="test",
    ) is result
    assert runnable.calls == 2


@pytest.mark.parametrize(
    "error",
    [
        type(
            "TooLargeError",
            (RuntimeError,),
            {"status_code": 413, "code": "rate_limit_exceeded"},
        )(),
        type(
            "QuotaError",
            (RuntimeError,),
            {"status_code": 429, "code": "insufficient_quota"},
        )(),
    ],
)
def test_structured_invocation_does_not_retry_payload_or_quota_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
) -> None:
    monkeypatch.setattr(llm, "get_settings", lambda: _settings())
    runnable = SyntheticRunnable([error])

    with pytest.raises(type(error)):
        llm.invoke_structured(
            runnable,
            messages=[("human", "Synthetic request.")],
            output_schema=SyntheticSchema,
            stage="test",
        )

    assert runnable.calls == 1


def test_structured_invocation_retries_transient_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "get_settings", lambda: _settings())
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)
    rate_limit_error = type(
        "TransientRateLimitError",
        (RuntimeError,),
        {"status_code": 429, "code": "rate_limit_exceeded"},
    )()
    expected_result = object()
    runnable = SyntheticRunnable([rate_limit_error, expected_result])

    result = llm.invoke_structured(
        runnable,
        messages=[("human", "Synthetic request.")],
        output_schema=SyntheticSchema,
        stage="test",
    )
    assert result is expected_result
    assert runnable.calls == 2


def test_structured_invocation_rejects_context_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm,
        "get_settings",
        lambda: _settings(max_input_tokens=1),
    )
    runnable = SyntheticRunnable([object()])

    with pytest.raises(llm.ModelContextLimitError):
        llm.invoke_structured(
            runnable,
            messages=[("human", "Synthetic request.")],
            output_schema=SyntheticSchema,
            stage="test",
        )

    assert runnable.calls == 0


def test_safe_retry_metadata_reads_only_retry_headers() -> None:
    error = RuntimeError("synthetic")
    error.headers = {
        "x-should-retry": "false",
        "retry-after": "4",
        "x-private-detail": "must not be returned",
    }

    assert llm.safe_retry_metadata(error) == {
        "provider_retry_hint": False,
        "retry_after_seconds": 4.0,
    }


def test_http_413_payload_too_large_never_maps_to_rate_limited() -> None:
    class SyntheticProviderError(RuntimeError):
        status_code = 413
        code = "rate_limit_exceeded"

    assert provider_failure_category(SyntheticProviderError()) == "payload_too_large"


# ---------------------------------------------------------------------------
# Google Gemini Secondary Fallback Provider Regression Tests
# ---------------------------------------------------------------------------


def _settings_with_gemini(
    *,
    gemini_api_key: str | None = "synthetic-gemini-key-do-not-log",
    gemini_model: str = "gemini-2.5-flash",
    groq_model: str = "openai/gpt-oss-120b",
    max_retries: int = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        groq_api_key=SecretStr("synthetic-groq-key-do-not-log"),
        groq_model=groq_model,
        groq_fallback_model=None,
        gemini_api_key=SecretStr(gemini_api_key) if gemini_api_key is not None else None,
        gemini_model=gemini_model,
        llm_temperature=0.0,
        groq_timeout_seconds=15.0,
        groq_max_input_tokens=24000,
        groq_max_output_tokens=4096,
        groq_tokenizer_encoding="o200k_harmony",
        groq_max_retries=max_retries,
        groq_max_retry_delay_seconds=5.0,
        groq_concurrency_limit=2,
        groq_pacing_delay_seconds=0.0,
    )


def test_groq_primary_success_records_groq_provider_without_invoking_gemini(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings_with_gemini()
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    gemini_factory = MagicMock()
    monkeypatch.setattr(llm, "get_gemini_chat_model", gemini_factory)

    expected = SyntheticSchema(value="groq-primary-ok")
    runnable = SyntheticRunnable([expected])

    result = llm.invoke_structured(
        runnable,
        messages=[("system", "System prompt"), ("human", "User input")],
        output_schema=SyntheticSchema,
        stage="intake_agent",
    )

    assert result == expected
    assert runnable.calls == 1
    gemini_factory.assert_not_called()

    diag = llm.get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "completed"
    assert diag["provider"] == "groq"
    assert diag["model"] == "openai/gpt-oss-120b"
    assert diag["primary_provider"] == "groq"
    assert diag["primary_model"] == "openai/gpt-oss-120b"
    assert diag["fallback_used"] is False
    assert "synthetic-groq-key-do-not-log" not in caplog.text
    assert "synthetic-gemini-key-do-not-log" not in caplog.text


def test_groq_429_immediately_falls_back_to_gemini_and_records_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings_with_gemini()
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    mock_limiter = MagicMock()
    monkeypatch.setattr(llm, "get_shared_rate_limiter", lambda: mock_limiter)

    class SyntheticGroq429Error(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"
        headers = {"retry-after": "25"}

    primary_runnable = SyntheticRunnable([SyntheticGroq429Error("Groq TPM exhausted")])

    # Mock official Google GenAI Client.models.generate_content
    mock_genai_client = MagicMock()
    mock_genai_response = SimpleNamespace(
        parsed=None,
        function_calls=None,
        text='{"value": "gemini-fallback-ok"}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=142,
            candidates_token_count=28,
            total_token_count=170,
        ),
    )
    mock_genai_client.models.generate_content.return_value = mock_genai_response

    gemini_model = llm.GeminiChatModel(
        model="gemini-2.5-flash",
        api_key="synthetic-gemini-key-do-not-log",
        temperature=0.0,
        timeout=15.0,
        max_tokens=4096,
        client=mock_genai_client,
    )
    monkeypatch.setattr(llm, "get_gemini_chat_model", lambda: gemini_model)

    result = llm.invoke_structured(
        primary_runnable,
        messages=[("system", "Extract structured schema."), ("human", "Test payload")],
        output_schema=SyntheticSchema,
        stage="evidence_analyst",
    )

    assert isinstance(result, SyntheticSchema)
    assert result.value == "gemini-fallback-ok"
    # Immediate failover on 429 without wasting retries on Groq
    assert primary_runnable.calls == 1
    mock_genai_client.models.generate_content.assert_called_once()
    call_kwargs = mock_genai_client.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["config"].response_mime_type == "application/json"
    assert call_kwargs["config"].response_schema is SyntheticSchema
    assert call_kwargs["config"].system_instruction == "Extract structured schema."

    diag = llm.get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "completed"
    assert diag["provider"] == "gemini"
    assert diag["model"] == "gemini-2.5-flash"
    assert diag["primary_provider"] == "groq"
    assert diag["primary_model"] == "openai/gpt-oss-120b"
    assert diag["fallback_used"] is True
    assert diag["fallback_provider"] == "gemini"
    assert diag["fallback_model_used"] == "gemini-2.5-flash"
    assert diag["primary_model_failure_category"] == "rate_limited"
    assert diag["primary_model_status_code"] == 429
    assert diag["primary_model_provider_code"] == "rate_limit_exceeded"
    assert diag["actual_prompt_tokens"] == 142
    assert diag["actual_completion_tokens"] == 28
    assert "synthetic-gemini-key-do-not-log" not in caplog.text
    assert "synthetic-groq-key-do-not-log" not in caplog.text


def test_groq_429_followed_by_gemini_failure_records_both_failures_and_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from google.genai import errors as genai_errors

    settings = _settings_with_gemini()
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "get_shared_rate_limiter", lambda: MagicMock())

    class SyntheticGroq429Error(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"

    primary_runnable = SyntheticRunnable([SyntheticGroq429Error("Groq 429")])

    mock_genai_client = MagicMock()
    gemini_api_err = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Gemini quota exceeded",
            }
        },
    )
    mock_genai_client.models.generate_content.side_effect = gemini_api_err

    gemini_model = llm.GeminiChatModel(
        model="gemini-2.5-flash",
        api_key="synthetic-gemini-key-do-not-log",
        client=mock_genai_client,
    )
    monkeypatch.setattr(llm, "get_gemini_chat_model", lambda: gemini_model)

    with pytest.raises(SyntheticGroq429Error):
        llm.invoke_structured(
            primary_runnable,
            messages=[("system", "System"), ("human", "Human")],
            output_schema=SyntheticSchema,
            stage="policy_analyst",
        )

    diag = llm.get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "unavailable"
    assert diag["category"] == "rate_limited"
    assert diag["status_code"] == 429
    assert diag["fallback_used"] is False
    assert diag["fallback_provider"] == "gemini"
    assert diag["fallback_model_attempted"] == "gemini-2.5-flash"
    assert diag["fallback_failure_category"] == "rate_limited"
    assert diag["fallback_status_code"] == 429
    assert diag["fallback_provider_code"] == "RESOURCE_EXHAUSTED"
    assert "synthetic-gemini-key-do-not-log" not in caplog.text


def test_gemini_structured_output_validation_and_tool_calling_for_specialist_schemas() -> None:
    from claimsage.agents.schemas import (
        RepairEstimateExtraction,
        SupervisorPlan,
    )

    mock_client = MagicMock()
    chat = llm.GeminiChatModel(
        model="gemini-2.5-flash",
        api_key="synthetic-gemini-key",
        client=mock_client,
    )

    # 1. Valid JSON structured output across specialist schemas
    valid_plan_json = (
        '{"selected_analysts": ["intake_agent", "evidence_analyst"], '
        '"routing_rationale": "Standard document and evidence review.", '
        '"human_review_required": true}'
    )
    mock_client.models.generate_content.return_value = SimpleNamespace(
        parsed=None,
        function_calls=None,
        text=f"```json\n{valid_plan_json}\n```",
        usage_metadata=None,
    )
    plan_runnable = chat.with_structured_output(SupervisorPlan, method="function_calling")
    plan_res = plan_runnable.invoke([("system", "Supervisor"), ("human", "Plan")])
    assert isinstance(plan_res, SupervisorPlan)
    assert plan_res.selected_analysts == ["intake_agent", "evidence_analyst"]

    # 2. Tool-calling response extraction via function_calls
    mock_client.models.generate_content.return_value = SimpleNamespace(
        parsed=None,
        function_calls=[
            SimpleNamespace(
                name="RepairEstimateExtraction",
                args={
                    "line_items": [
                        {
                            "description": "Front bumper assembly",
                            "quantity": "1",
                            "unit_price": "INR 14,000",
                            "reported_amount": "INR 12,600",
                            "source_evidence_ids": ["ev-1"],
                        }
                    ],
                    "clarification_needs": [],
                    "missing_information": [],
                    "extraction_complete": True,
                },
            )
        ],
        text=None,
        usage_metadata=None,
    )
    est_runnable = chat.with_structured_output(
        RepairEstimateExtraction,
        method="function_calling",
    )
    est_res = est_runnable.invoke([("system", "Repair"), ("human", "Extract")])
    assert isinstance(est_res, RepairEstimateExtraction)
    assert len(est_res.line_items) == 1
    assert est_res.line_items[0].description == "Front bumper assembly"

    # 3. Direct bind_tools support
    tool_runnable = chat.bind_tools([SupervisorPlan])
    mock_client.models.generate_content.return_value = SimpleNamespace(
        function_calls=[
            SimpleNamespace(
                name="SupervisorPlan",
                args={
                    "selected_analysts": ["policy_analyst"],
                    "routing_rationale": "Check policy wording.",
                    "human_review_required": True,
                },
            )
        ]
    )
    bound_res = tool_runnable.invoke([("system", "Route"), ("human", "Task")])
    assert isinstance(bound_res, SupervisorPlan)
    assert bound_res.selected_analysts == ["policy_analyst"]

    # 4. Malformed / schema-invalid response is rejected with GeminiStructuredOutputError
    mock_client.models.generate_content.return_value = SimpleNamespace(
        parsed=None,
        function_calls=None,
        text='{"invalid_field": 123}',
        usage_metadata=None,
    )
    with pytest.raises(llm.GeminiStructuredOutputError):
        plan_runnable.invoke([("system", "Supervisor"), ("human", "Plan")])


def test_complete_investigation_with_groq_429_and_gemini_fallback_vs_both_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4
    from claimsage.agents import graph as graph_module
    from claimsage.agents.schemas import (
        ClaimEvidenceFinding,
        EvidenceAnalystOutput,
        IntakeDocumentInventoryItem,
        IntakeDocumentOutput,
        PolicyAnalystOutput,
        PolicyClauseFinding,
        PolicyEvidenceQuote,
        ReviewReportAnalystOutputReference,
        ReviewReportExtraction,
        ReviewReportItemExtraction,
        RiskAnomalyExtraction,
        SupervisorPlan,
    )

    settings = _settings_with_gemini()
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    monkeypatch.setattr(graph_module, "get_settings", lambda: settings)
    monkeypatch.setattr(llm, "get_shared_rate_limiter", lambda: MagicMock())

    claim_ev_id = str(uuid4())
    policy_ev_id = str(uuid4())
    claim_doc_id = uuid4()
    policy_doc_id = uuid4()

    claim_chunk = SimpleNamespace(
        chunk_id=claim_ev_id,
        document_id=claim_doc_id,
        filename="synthetic_claim_bill.pdf",
        page_number=1,
        chunk_index=0,
        text="Itemized Hospital Bill: Room rent INR 4,500 per day for 3 days.",
        similarity=0.91,
        embedding_model="test-model",
        extraction_method="native",
        ocr_confidence=None,
    )
    policy_chunk = SimpleNamespace(
        chunk_id=policy_ev_id,
        document_id=policy_doc_id,
        filename="synthetic_health_policy_v1.pdf",
        page_number=2,
        chunk_index=0,
        text="Clause 2.1 Covered Benefits: In-patient hospitalization room rent limit INR 5,000 per day.",
        similarity=0.89,
        embedding_model="test-model",
        clause_id=uuid4(),
        clause_identifier="2.1",
        clause_category="coverage",
        verification_status="verified",
        policy_version="v1",
        source_url=None,
        insurer_name="Synthetic Health Insurer",
        product_name="Health Shield",
        effective_from=None,
        effective_to=None,
    )

    monkeypatch.setattr(
        graph_module,
        "retrieve_authorized_claim",
        lambda session, *, employee_id, claim_id: {
            "claim_id": str(claim_id),
            "claim_number": "CLM-SYNTH-HEALTH-01",
            "claim_type": "health",
            "policy_identifier": "POL-SYNTH-HEALTH-V1",
            "status": "under_review",
            "loss_date": "2026-10-10",
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

    class SyntheticGroq429Error(RuntimeError):
        status_code = 429
        code = "rate_limit_exceeded"

    # Primary Groq model always fails with HTTP 429
    failing_groq_structured = MagicMock()
    failing_groq_structured.invoke.side_effect = SyntheticGroq429Error("Groq 429")
    failing_groq_chat = MagicMock()
    failing_groq_chat.with_structured_output.return_value = failing_groq_structured

    for mod_path in (
        "claimsage.agents.supervisor.get_chat_model",
        "claimsage.agents.intake_agent.get_chat_model",
        "claimsage.agents.evidence_analyst.get_chat_model",
        "claimsage.agents.policy_analyst.get_chat_model",
        "claimsage.agents.risk_anomaly_agent.get_chat_model",
        "claimsage.agents.review_report_agent.get_chat_model",
    ):
        monkeypatch.setattr(mod_path, lambda: failing_groq_chat)

    # Part A: Gemini fallback succeeds for every stage
    def fake_gemini_generate_content(*, model, contents, config):
        schema = config.response_schema
        if schema is SupervisorPlan:
            parsed = SupervisorPlan(
                selected_analysts=[
                    "intake_agent",
                    "evidence_analyst",
                    "policy_analyst",
                    "risk_anomaly_agent",
                ],
                routing_rationale="Selected all applicable health claim specialists.",
                human_review_required=True,
            )
        elif schema is IntakeDocumentOutput:
            parsed = IntakeDocumentOutput(
                summary="Extracted hospital bill details.",
                extracted_fields=[],
                document_flags=[],
                document_inventory=[
                    IntakeDocumentInventoryItem(
                        filename="synthetic_claim_bill.pdf",
                        document_type="hospital_bill",
                        status="complete",
                        source_evidence_ids=[claim_ev_id],
                    )
                ],
                missing_information=[],
                overall_assessment="documents_sufficient",
                human_review_required=True,
            )
        elif schema is EvidenceAnalystOutput:
            parsed = EvidenceAnalystOutput(
                summary="Hospital bill shows room rent of INR 4,500 per day.",
                factual_findings=[
                    ClaimEvidenceFinding(
                        finding="Itemized Hospital Bill: Room rent INR 4,500 per day for 3 days.",
                        supporting_evidence_ids=[claim_ev_id],
                        explanation="Directly stated on page 1 of the itemized hospital bill.",
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
        elif schema is PolicyAnalystOutput:
            parsed = PolicyAnalystOutput(
                summary="Policy provides in-patient room rent coverage up to INR 5,000 per day.",
                relevant_clauses=[
                    PolicyClauseFinding(
                        finding="In-patient hospitalization room rent limit INR 5,000 per day.",
                        explanation="Room rent is capped at INR 5,000 per day.",
                        supporting_evidence_ids=[policy_ev_id],
                        supporting_quotes=[
                            PolicyEvidenceQuote(
                                evidence_id=policy_ev_id,
                                quote="In-patient hospitalization room rent limit INR 5,000 per day.",
                            )
                        ],
                        confidence="high",
                    )
                ],
                coverage_indicators=[],
                exclusions_and_conditions=[],
                missing_information=[],
                evidence_gaps=[],
                overall_assessment="potentially_supportive",
                human_review_required=True,
            )
        elif schema is RiskAnomalyExtraction:
            parsed = RiskAnomalyExtraction(
                observed_facts=[],
                anomalies=[],
                hypotheses=[],
                missing_information=[],
            )
        elif schema is ReviewReportExtraction:
            parsed = ReviewReportExtraction(
                observed_facts=[
                    ReviewReportItemExtraction(
                        statement="Itemized Hospital Bill: Room rent INR 4,500 per day for 3 days.",
                        explanation="Verified from hospital bill.",
                        supporting_evidence_ids=[claim_ev_id],
                        supporting_quotes=[
                            {
                                "evidence_id": claim_ev_id,
                                "quote": "Itemized Hospital Bill: Room rent INR 4,500 per day for 3 days.",
                            }
                        ],
                    )
                ],
                analyst_interpretations=[
                    ReviewReportItemExtraction(
                        statement="In-patient hospitalization room rent limit INR 5,000 per day.",
                        explanation="Policy Analyst identified the room rent limit.",
                        supporting_evidence_ids=[policy_ev_id],
                        supporting_quotes=[
                            {
                                "evidence_id": policy_ev_id,
                                "quote": "In-patient hospitalization room rent limit INR 5,000 per day.",
                            }
                        ],
                        analyst_output_references=[
                            ReviewReportAnalystOutputReference(
                                specialist="policy_analyst",
                                output_path="/relevant_clauses/0/finding",
                                finding_text="In-patient hospitalization room rent limit INR 5,000 per day.",
                            )
                        ],
                    )
                ],
                hypotheses=[],
                conflicting_findings=[],
                missing_information=[],
            )
        else:
            raise AssertionError(f"Unexpected schema {schema}")

        return SimpleNamespace(
            parsed=parsed,
            function_calls=None,
            text=None,
            usage_metadata=SimpleNamespace(
                prompt_token_count=200,
                candidates_token_count=80,
                total_token_count=280,
            ),
        )

    mock_genai_client = MagicMock()
    mock_genai_client.models.generate_content.side_effect = fake_gemini_generate_content
    gemini_chat = llm.GeminiChatModel(
        model="gemini-2.5-flash",
        api_key="synthetic-gemini-key",
        client=mock_genai_client,
    )
    monkeypatch.setattr(llm, "get_gemini_chat_model", lambda: gemini_chat)

    state_ok = graph_module.run_investigation(
        session=MagicMock(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Investigate synthetic health claim.",
    )

    assert state_ok["review_report_status"] == "completed"
    assert state_ok["review_report"] is not None
    assert state_ok["review_report"].overall_status == "completed"
    assert state_ok["review_report"].report_generation_mode == "ai_generated"

    stage_diags = state_ok["result"]["stage_diagnostics"]
    for stage_key in (
        "supervisor",
        "intake_analysis",
        "evidence_analysis",
        "policy_analysis",
        "risk_analysis",
        "review_report",
    ):
        assert stage_diags[stage_key]["status"] == "completed"
        assert stage_diags[stage_key]["provider"] == "gemini"
        assert stage_diags[stage_key]["model"] == "gemini-2.5-flash"
        assert stage_diags[stage_key]["fallback_used"] is True
        assert stage_diags[stage_key]["primary_model_status_code"] == 429

    # Part B: Both Groq and Gemini fail -> preserves completed results and generates deterministic fallback report
    mock_genai_client.models.generate_content.side_effect = RuntimeError("Gemini unavailable")
    state_both_fail = graph_module.run_investigation(
        session=MagicMock(),
        employee_id=uuid4(),
        claim_id=uuid4(),
        task="Investigate synthetic health claim when both providers fail.",
    )
    assert state_both_fail["intake_analysis_status"] == "unavailable"
    assert state_both_fail["evidence_analysis_status"] == "unavailable"
    assert state_both_fail["policy_analysis_status"] == "unavailable"
    assert state_both_fail["review_report_status"] == "incomplete"
    assert state_both_fail["review_report"] is not None
    assert state_both_fail["review_report"].report_generation_mode == "deterministic_fallback"
    assert state_both_fail["review_report"].overall_status == "incomplete"
    assert state_both_fail["result"]["stage_diagnostics"]["intake_analysis"]["fallback_provider"] == "gemini"
    assert state_both_fail["result"]["stage_diagnostics"]["intake_analysis"]["fallback_model_attempted"] == "gemini-2.5-flash"
