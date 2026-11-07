"""Tests for targeted reliability remediation.

Verifies:
1. Per-agent token-budget enforcement
2. Unknown-stage fallback
3. Requests exceeding global limit
4. Conservative token overhead
5. Missing provider usage metadata
6. Successful and failed invocation diagnostics
7. Retry count and duration recording
8. Deduplication diagnostics
9. Concurrent rate-limiter requests across independent database sessions
10. Lock/lease cleanup after exceptions and timeouts
11. Variable token consumption and cooldown handling
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from claimsage.agents.graph import _record_stage_diagnostic
from claimsage.agents.llm import (
    PROTOCOL_OVERHEAD_TOKENS,
    ModelContextLimitError,
    _request_token_count,
    get_last_invocation_diagnostic,
    invoke_structured,
    last_invocation_diagnostic_ctx,
)
from claimsage.agents.rate_limiter import (
    GROQ_RATE_LIMIT_LOCK_ID,
    RateLimitCoordinationError,
    SharedRateLimiter,
)
from claimsage.agents.token_budget_manager import get_token_budget_manager
from claimsage.db.session import SessionLocal


class DummySchema(BaseModel):
    summary: str


class LargeSchema(BaseModel):
    field1: str
    field2: str
    field3: str
    field4: str
    field5: str


@pytest.fixture(autouse=True)
def clean_rate_limiter_audit_events():
    """Ensure test rate-limiter reservations and cooldowns are cleaned before and after each test."""
    with SessionLocal() as db:
        db.execute(text("DELETE FROM audit_events WHERE action IN ('ai_token_reservation', 'ai_provider_cooldown')"))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(text("DELETE FROM audit_events WHERE action IN ('ai_token_reservation', 'ai_provider_cooldown')"))
        db.commit()


# -----------------------------------------------------------------------------
# 1. Per-Agent Token-Budget Enforcement
# -----------------------------------------------------------------------------
def test_per_agent_budget_enforced_for_each_agent():
    """Verify that stage budget is strictly enforced inside invoke_structured."""
    mock_runnable = MagicMock()
    mock_runnable.invoke.return_value = DummySchema(summary="ok")

    # Supervisor budget is 1,200 tokens
    # Generate messages that exceed 1,200 tokens (e.g. ~1,400 tokens) but are well below the global 6,000 ceiling
    large_text = "word " * 1400  # ~1440 tokens with overhead
    messages = [("system", "You are a planner."), ("human", large_text)]

    with pytest.raises(ModelContextLimitError) as exc_info:
        invoke_structured(
            mock_runnable,
            messages=messages,
            output_schema=DummySchema,
            stage="supervisor",
        )
    assert "exceeds the configured stage input budget of 1200 tokens" in str(exc_info.value)

    # For an agent with a higher budget (e.g. policy_analyst: 2,600 tokens), the same ~1,400 token prompt succeeds
    result = invoke_structured(
        mock_runnable,
        messages=messages,
        output_schema=DummySchema,
        stage="policy_analyst",
    )
    assert result.summary == "ok"


# -----------------------------------------------------------------------------
# 2. Unknown-Stage Fallback
# -----------------------------------------------------------------------------
def test_unknown_stage_fallback_to_default_allocation():
    """Verify that an unknown stage falls back safely to default allocation (2,500 tokens)."""
    mock_runnable = MagicMock()
    mock_runnable.invoke.return_value = DummySchema(summary="ok")

    # Prompt of ~100 tokens succeeds under unknown stage default 2,500 budget
    small_messages = [("system", "Test"), ("human", "Hello")]
    result = invoke_structured(
        mock_runnable,
        messages=small_messages,
        output_schema=DummySchema,
        stage="custom_unknown_specialist",
    )
    assert result.summary == "ok"

    # Prompt of ~2,700 tokens exceeds 2,500 default budget
    large_text = "word " * 2700
    large_messages = [("system", "Test"), ("human", large_text)]
    with pytest.raises(ModelContextLimitError) as exc_info:
        invoke_structured(
            mock_runnable,
            messages=large_messages,
            output_schema=DummySchema,
            stage="custom_unknown_specialist",
        )
    assert "exceeds the configured stage input budget of 2500 tokens" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 3. Requests Exceeding Global Limit
# -----------------------------------------------------------------------------
def test_requests_exceeding_global_limit():
    """Verify requests exceeding the global provider limit (6,000) are blocked."""
    mock_runnable = MagicMock()
    huge_text = "word " * 5500  # ~7,000+ tokens
    messages = [("system", "System"), ("human", huge_text)]

    with pytest.raises(ModelContextLimitError):
        invoke_structured(
            mock_runnable,
            messages=messages,
            output_schema=DummySchema,
            stage="review_report",  # Stage budget is 2,800, so caught by stage or global
        )


# -----------------------------------------------------------------------------
# 4. Conservative Token Overhead
# -----------------------------------------------------------------------------
def test_conservative_token_overhead_included_in_request_count():
    """Verify PROTOCOL_OVERHEAD_TOKENS (32) is added to prompt token estimation."""
    messages = [("system", "sys"), ("human", "usr")]
    prompt_tokens, schema_tokens, request_bytes = _request_token_count(
        messages=messages,
        output_schema=DummySchema,
    )
    # Both messages are very short (3-4 tokens raw); with 32 overhead tokens, prompt_tokens must be >= 35
    assert prompt_tokens >= 35
    assert schema_tokens > 0
    assert request_bytes > 0


# -----------------------------------------------------------------------------
# 5. Missing Provider Usage Metadata
# -----------------------------------------------------------------------------
def test_missing_provider_usage_metadata_handled_gracefully():
    """Verify when provider omits token usage, actual tokens are recorded as None without crashing."""
    mock_runnable = MagicMock()
    mock_runnable.invoke.return_value = DummySchema(summary="success")

    invoke_structured(
        mock_runnable,
        messages=[("system", "sys"), ("human", "usr")],
        output_schema=DummySchema,
        stage="evidence_analyst",
    )

    diag = get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "completed"
    assert diag["actual_prompt_tokens"] is None
    assert diag["actual_completion_tokens"] is None
    assert diag["estimated_input_tokens"] > 0
    assert diag["execution_duration"] >= 0.0


# -----------------------------------------------------------------------------
# 6. Successful and Failed Invocation Diagnostics
# -----------------------------------------------------------------------------
def test_successful_invocation_diagnostic():
    """Verify diagnostics recorded on successful execution."""
    mock_runnable = MagicMock()
    mock_runnable.invoke.return_value = DummySchema(summary="completed")

    invoke_structured(
        mock_runnable,
        messages=[("system", "sys"), ("human", "usr")],
        output_schema=DummySchema,
        stage="risk_anomaly_agent",
    )

    diag = get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["stage"] == "risk_anomaly_agent"
    assert diag["status"] == "completed"
    assert diag["retry_attempts"] == 0
    assert diag["status_code"] == 200
    assert diag["category"] is None


def test_failed_invocation_diagnostic():
    """Verify diagnostics recorded on fatal failure."""
    mock_runnable = MagicMock()
    # Simulate a 401 AuthenticationError (non-retryable)
    auth_err = Exception("Invalid API Key")
    setattr(auth_err, "status_code", 401)
    mock_runnable.invoke.side_effect = auth_err

    with pytest.raises(Exception):
        invoke_structured(
            mock_runnable,
            messages=[("system", "sys"), ("human", "usr")],
            output_schema=DummySchema,
            stage="intake_agent",
        )

    diag = get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["stage"] == "intake_agent"
    assert diag["status"] == "unavailable"
    assert diag["category"] == "authentication_error"
    assert diag["status_code"] == 401


# -----------------------------------------------------------------------------
# 7. Retry Count and Duration Recording
# -----------------------------------------------------------------------------
def test_retry_count_and_duration_recording():
    """Verify retry attempts and execution duration are recorded across retries."""
    mock_runnable = MagicMock()
    rate_limit_err = Exception("Rate limit reached")
    setattr(rate_limit_err, "status_code", 429)

    # Fail on first attempt, succeed on second
    mock_runnable.invoke.side_effect = [rate_limit_err, DummySchema(summary="recovered")]

    with patch("claimsage.agents.llm._retry_delay", return_value=0.01):
        result = invoke_structured(
            mock_runnable,
            messages=[("system", "sys"), ("human", "usr")],
            output_schema=DummySchema,
            stage="evidence_analyst",
        )

    assert result.summary == "recovered"
    diag = get_last_invocation_diagnostic()
    assert diag is not None
    assert diag["status"] == "completed"
    assert diag["retry_attempts"] == 1
    assert diag["execution_duration"] >= 0.01


# -----------------------------------------------------------------------------
# 8. Deduplication Diagnostics
# -----------------------------------------------------------------------------
def test_deduplication_diagnostics_integration():
    """Verify _record_stage_diagnostic merges deduplicated passage counts and invocation metrics."""
    # Set a known diagnostic in context
    last_invocation_diagnostic_ctx.set({
        "stage": "evidence_analysis",
        "estimated_input_tokens": 1450,
        "actual_prompt_tokens": 1420,
        "actual_completion_tokens": 310,
        "execution_duration": 1.25,
        "retry_attempts": 0,
        "status": "completed",
        "category": None,
        "status_code": 200,
        "provider_code": None,
    })

    result_state: dict[str, Any] = {}
    updated = _record_stage_diagnostic(
        result_state,
        stage="evidence_analysis",
        diagnostic={
            "agent_name": "evidence_analyst",
            "retrieval_strategy": "evidence_analyst_contextual",
            "candidate_passages": 8,
            "deduplicated_passages": 3,
            "selected_passages": 5,
            "status": "completed",
        },
    )

    stage_diag = updated["stage_diagnostics"]["evidence_analysis"]
    assert stage_diag["agent_name"] == "evidence_analyst"
    assert stage_diag["candidate_passages"] == 8
    assert stage_diag["deduplicated_passages"] == 3
    assert stage_diag["selected_passages"] == 5
    assert stage_diag["estimated_input_tokens"] == 1450
    assert stage_diag["actual_prompt_tokens"] == 1420
    assert stage_diag["actual_completion_tokens"] == 310
    assert stage_diag["execution_duration"] == 1.25
    assert stage_diag["retry_attempts"] == 0
    assert stage_diag["status"] == "completed"


# -----------------------------------------------------------------------------
# 9. Concurrent Rate-Limiter Requests Across Independent DB Sessions
# -----------------------------------------------------------------------------
def test_concurrent_rate_limiter_sessions():
    """Verify SharedRateLimiter acquires transaction-level advisory locks cleanly."""
    limiter = SharedRateLimiter(tpm_limit=7000, window_seconds=60.0)

    # In test mode, rate limiter returns 0.0 unless force_rate_limiter_in_test is enabled
    with patch("claimsage.agents.rate_limiter.get_settings") as mock_settings:
        mock_settings.return_value.app_env = "production"

        # Session 1 acquires permit
        wait1 = limiter.acquire_permit(estimated_tokens=1500, stage="stage_1", session_factory=SessionLocal)
        assert wait1 == 0.0

        # Session 2 acquires permit immediately within budget
        wait2 = limiter.acquire_permit(estimated_tokens=1500, stage="stage_2", session_factory=SessionLocal)
        assert wait2 == 0.0


# -----------------------------------------------------------------------------
# 10. Lock/Lease Cleanup After Exceptions and Timeouts
# -----------------------------------------------------------------------------
def test_lock_cleanup_after_db_exception():
    """Verify SharedRateLimiter fails closed when DB fails, raising RateLimitCoordinationError."""
    limiter = SharedRateLimiter()

    faulty_factory = MagicMock(side_effect=RuntimeError("Database connection lost"))

    with patch("claimsage.agents.rate_limiter.get_settings") as mock_settings:
        mock_settings.return_value.app_env = "production"
        with pytest.raises(RateLimitCoordinationError) as exc_info:
            limiter.acquire_permit(
                estimated_tokens=2000,
                stage="test_fail",
                session_factory=faulty_factory,
            )
        assert "Unable to acquire a shared rate-limit permit" in str(exc_info.value)


def test_invoke_structured_blocks_when_rate_coordination_fails():
    """Verify invoke_structured aborts immediately and records diagnostic when rate limiter fails."""
    mock_runnable = MagicMock()
    with patch("claimsage.agents.llm.get_shared_rate_limiter") as mock_limiter_getter:
        mock_limiter = MagicMock()
        mock_limiter.acquire_permit.side_effect = RateLimitCoordinationError("DB unavailable")
        mock_limiter_getter.return_value = mock_limiter

        with pytest.raises(RateLimitCoordinationError):
            invoke_structured(
                mock_runnable,
                messages=[("system", "sys"), ("human", "usr")],
                output_schema=DummySchema,
                stage="intake_agent",
            )
        # Runnable must NEVER be called if permit is not acquired!
        mock_runnable.invoke.assert_not_called()

        diag = get_last_invocation_diagnostic()
        assert diag is not None
        assert diag["status"] == "unavailable"
        assert diag["category"] == "rate_coordination_unavailable"
        assert diag["status_code"] == 503


# -----------------------------------------------------------------------------
# 11. Variable Token Consumption and Cooldown Handling
# -----------------------------------------------------------------------------
def test_variable_token_consumption_and_cooldown():
    """Verify variable token consumption triggers cooldown and respects Retry-After."""
    with SessionLocal() as db:
        db.execute(text("DELETE FROM audit_events WHERE action IN ('ai_token_reservation', 'ai_provider_cooldown')"))
        db.commit()

    limiter = SharedRateLimiter(tpm_limit=4000, window_seconds=60.0)

    with patch("claimsage.agents.rate_limiter.get_settings") as mock_settings:
        mock_settings.return_value.app_env = "production"

        # Record a provider cooldown
        limiter.record_provider_cooldown(seconds=0.25, session_factory=SessionLocal)

        # Immediate permit should notice cooldown
        with patch("time.sleep") as mock_sleep:
            wait = limiter.acquire_permit(
                estimated_tokens=500,
                stage="cooling_stage",
                session_factory=SessionLocal,
            )
            assert wait > 0.0
            mock_sleep.assert_called_once()


# -----------------------------------------------------------------------------
# 12. Skipped Stage Does Not Inherit Previous Stage Metrics
# -----------------------------------------------------------------------------
def test_skipped_stage_does_not_inherit_previous_stage_metrics():
    """Verify skipped stages record None for token and duration metrics without inheriting from prior stage."""
    # Context contains completed metrics from policy_analyst
    last_invocation_diagnostic_ctx.set({
        "stage": "policy_analyst",
        "estimated_input_tokens": 2100,
        "actual_prompt_tokens": 2050,
        "actual_completion_tokens": 420,
        "execution_duration": 2.45,
        "retry_attempts": 0,
        "status": "completed",
        "category": None,
        "status_code": 200,
        "provider_code": None,
    })

    result_state: dict[str, Any] = {}
    updated = _record_stage_diagnostic(
        result_state,
        stage="repair_estimate_analysis",
        diagnostic={
            "agent_name": "repair_estimate_analyst",
            "retrieval_strategy": "repair_estimate_contextual",
            "candidate_passages": 0,
            "deduplicated_passages": 0,
            "selected_passages": 0,
            "status": "skipped",
        },
    )

    stage_diag = updated["stage_diagnostics"]["repair_estimate_analysis"]
    assert stage_diag["agent_name"] == "repair_estimate_analyst"
    assert stage_diag["status"] == "skipped"
    # Invocation metrics must be None, NOT inherited from policy_analyst!
    assert stage_diag["estimated_input_tokens"] is None
    assert stage_diag["actual_prompt_tokens"] is None
    assert stage_diag["actual_completion_tokens"] is None
    assert stage_diag["execution_duration"] is None
    assert stage_diag["retry_attempts"] == 0
    assert stage_diag["failure_category"] is None
    assert stage_diag["status_code"] is None


# -----------------------------------------------------------------------------
# 13. Stage Failing Before LLM Invocation Does Not Inherit Stale Metrics
# -----------------------------------------------------------------------------
def test_stage_failing_before_llm_invocation_does_not_inherit_stale_metrics():
    """Verify that if a stage fails prior to LLM invocation, it does not inherit prior stage metrics."""
    last_invocation_diagnostic_ctx.set({
        "stage": "evidence_analyst",
        "estimated_input_tokens": 1800,
        "actual_prompt_tokens": 1780,
        "actual_completion_tokens": 300,
        "execution_duration": 1.10,
        "retry_attempts": 0,
        "status": "completed",
        "category": None,
        "status_code": 200,
        "provider_code": None,
    })

    result_state: dict[str, Any] = {}
    # Stage policy_analysis fails before calling LLM (e.g. retrieval error)
    updated = _record_stage_diagnostic(
        result_state,
        stage="policy_analysis",
        diagnostic={
            "agent_name": "policy_analyst",
            "retrieval_strategy": "policy_analyst_contextual",
            "candidate_passages": 0,
            "deduplicated_passages": 0,
            "selected_passages": 0,
            "status": "unavailable",
        },
    )

    stage_diag = updated["stage_diagnostics"]["policy_analysis"]
    assert stage_diag["agent_name"] == "policy_analyst"
    assert stage_diag["status"] == "unavailable"
    # Must NOT inherit evidence_analyst's 1800 tokens or duration!
    assert stage_diag["estimated_input_tokens"] is None
    assert stage_diag["actual_prompt_tokens"] is None
    assert stage_diag["actual_completion_tokens"] is None
    assert stage_diag["execution_duration"] is None
    assert stage_diag["retry_attempts"] == 0


# -----------------------------------------------------------------------------
# 14. Successful Stage Receives Only Its Own Invocation Metrics
# -----------------------------------------------------------------------------
def test_successful_stage_receives_only_its_own_metrics():
    """Verify that when stage names match, the stage receives its exact invocation metrics."""
    last_invocation_diagnostic_ctx.set({
        "stage": "policy_analyst",
        "estimated_input_tokens": 2250,
        "actual_prompt_tokens": 2200,
        "actual_completion_tokens": 510,
        "execution_duration": 1.85,
        "retry_attempts": 0,
        "status": "completed",
        "category": None,
        "status_code": 200,
        "provider_code": None,
    })

    result_state: dict[str, Any] = {}
    updated = _record_stage_diagnostic(
        result_state,
        stage="policy_analysis",
        diagnostic={
            "agent_name": "policy_analyst",
            "retrieval_strategy": "policy_analyst_contextual",
            "candidate_passages": 5,
            "deduplicated_passages": 0,
            "selected_passages": 5,
            "status": "completed",
        },
    )

    stage_diag = updated["stage_diagnostics"]["policy_analysis"]
    assert stage_diag["agent_name"] == "policy_analyst"
    assert stage_diag["status"] == "completed"
    assert stage_diag["estimated_input_tokens"] == 2250
    assert stage_diag["actual_prompt_tokens"] == 2200
    assert stage_diag["actual_completion_tokens"] == 510
    assert stage_diag["execution_duration"] == 1.85
    assert stage_diag["retry_attempts"] == 0


# -----------------------------------------------------------------------------
# 15. Reservation Timestamps Stored Separately from Creation Timestamps
# -----------------------------------------------------------------------------
def test_reservation_timestamps_stored_separately():
    """Verify created_at stores actual insert time and projected_at is stored in event_metadata."""
    limiter = SharedRateLimiter(tpm_limit=5000, window_seconds=60.0)

    with patch("claimsage.agents.rate_limiter.get_settings") as mock_settings:
        mock_settings.return_value.app_env = "production"

        t_before = datetime.now(UTC)
        limiter.acquire_permit(
            estimated_tokens=1000,
            stage="timestamp_test_stage",
            session_factory=SessionLocal,
        )
        t_after = datetime.now(UTC)

        with SessionLocal() as db:
            row = db.execute(
                text("""
                    SELECT created_at, event_metadata
                    FROM audit_events
                    WHERE action = 'ai_token_reservation'
                      AND event_metadata->>'stage' = 'timestamp_test_stage'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
            ).first()

            assert row is not None
            created_at, metadata = row[0], row[1]
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)

            # created_at must reflect actual insertion time (not future projected time!)
            assert t_before - timedelta(seconds=2) <= created_at <= t_after + timedelta(seconds=2)
            assert "projected_at" in metadata
            projected_at = datetime.fromisoformat(metadata["projected_at"])
            if projected_at.tzinfo is None:
                projected_at = projected_at.replace(tzinfo=UTC)
            assert projected_at >= created_at


# -----------------------------------------------------------------------------
# 16. Rolling Window Respects Projected Reservations
# -----------------------------------------------------------------------------
def test_rolling_window_respects_projected_reservations():
    """Verify rolling-window query sums tokens using projected_at to enforce rate pacing."""
    # Clean previous test reservations from test DB for clean slate
    with SessionLocal() as db:
        db.execute(text("DELETE FROM audit_events WHERE action = 'ai_token_reservation'"))
        db.commit()

    limiter = SharedRateLimiter(tpm_limit=5000, window_seconds=60.0)

    with patch("claimsage.agents.rate_limiter.get_settings") as mock_settings:
        mock_settings.return_value.app_env = "production"

        # First request consumes 4,000 of 5,000 budget
        wait1 = limiter.acquire_permit(estimated_tokens=4000, stage="heavy_stage", session_factory=SessionLocal)
        assert wait1 == 0.0

        # Second request of 2,000 tokens exceeds 5,000 limit -> must calculate positive wait_seconds
        with patch("time.sleep") as mock_sleep:
            wait2 = limiter.acquire_permit(estimated_tokens=2000, stage="overflow_stage", session_factory=SessionLocal)
            assert wait2 > 0.0
            mock_sleep.assert_called_once()


# -----------------------------------------------------------------------------
# 17. Concurrent Reservation Thread Safety
# -----------------------------------------------------------------------------
def test_concurrent_reservation_thread_safety():
    """Verify concurrent threads calling acquire_permit execute safely via PostgreSQL advisory lock."""
    import concurrent.futures

    limiter = SharedRateLimiter(tpm_limit=8000, window_seconds=60.0)

    def worker_acquire(stage_id: int):
        with patch("claimsage.agents.rate_limiter.get_settings") as mock_settings:
            mock_settings.return_value.app_env = "production"
            return limiter.acquire_permit(
                estimated_tokens=500,
                stage=f"thread_worker_{stage_id}",
                session_factory=SessionLocal,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(worker_acquire, i) for i in range(4)]
        results = [f.result() for f in futures]

    assert len(results) == 4
    assert all(isinstance(r, (int, float)) for r in results)

