"""Groq primary and Google Gemini fallback language model providers for ClaimSage agents."""

import json
import logging
import random
import re
import threading
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any, Protocol
from contextvars import ContextVar

import tiktoken
from google import genai
from google.genai import types as genai_types
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_groq import ChatGroq
from pydantic import BaseModel, ValidationError

from claimsage.core.config import get_settings
from claimsage.core.observability import investigation_id_ctx
from claimsage.agents.token_budget_manager import get_token_budget_manager
from claimsage.agents.rate_limiter import (
    RateLimitCoordinationError,
    get_shared_rate_limiter,
)

logger = logging.getLogger(__name__)
_SAFE_PROVIDER_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_MAX_PROVIDER_ATTEMPTS = 3
_MAX_RETRY_DELAY_SECONDS = 5.0
_MODEL_SEMAPHORE: threading.BoundedSemaphore | None = None
_MODEL_SEMAPHORE_LIMIT: int | None = None
_SEMAPHORE_LOCK = threading.Lock()

# Conservative chat protocol framing tokens (e.g. <|im_start|>, <|im_end|>, priming)
# plus provider-side JSON Schema wrapper instruction overhead.
PROTOCOL_OVERHEAD_TOKENS = 32

last_invocation_diagnostic_ctx: ContextVar[dict[str, Any] | None] = ContextVar(
    "last_invocation_diagnostic", default=None
)


def get_last_invocation_diagnostic() -> dict[str, Any] | None:
    """Return invocation diagnostic metrics captured during the most recent LLM call."""
    return last_invocation_diagnostic_ctx.get()


class UsageCaptureCallbackHandler(BaseCallbackHandler):
    """Captures actual provider token usage metadata from LangChain LLM execution."""

    def __init__(self) -> None:
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None
        self.total_tokens: int | None = None

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            llm_output = response.llm_output or {}
            usage = llm_output.get("token_usage") or {}
            if not usage and response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        msg = getattr(gen, "message", None)
                        if msg:
                            meta = getattr(msg, "response_metadata", {}) or {}
                            usage = meta.get("token_usage") or meta.get("usage") or {}
                            if usage:
                                break
                    if usage:
                        break

            if isinstance(usage, dict):
                self.prompt_tokens = usage.get("prompt_tokens")
                self.completion_tokens = usage.get("completion_tokens")
                self.total_tokens = usage.get("total_tokens")
        except Exception:
            pass



def get_model_semaphore() -> threading.BoundedSemaphore:
    """Return the bounded semaphore configured from application settings."""
    global _MODEL_SEMAPHORE, _MODEL_SEMAPHORE_LIMIT
    settings = get_settings()
    configured_limit = max(1, getattr(settings, "groq_concurrency_limit", 2))
    with _SEMAPHORE_LOCK:
        if _MODEL_SEMAPHORE is None or _MODEL_SEMAPHORE_LIMIT != configured_limit:
            _MODEL_SEMAPHORE = threading.BoundedSemaphore(value=configured_limit)
            _MODEL_SEMAPHORE_LIMIT = configured_limit
        return _MODEL_SEMAPHORE


def reset_model_semaphore() -> None:
    """Reset cached semaphore so tests can verify dynamic concurrency limits."""
    global _MODEL_SEMAPHORE, _MODEL_SEMAPHORE_LIMIT
    with _SEMAPHORE_LOCK:
        _MODEL_SEMAPHORE = None
        _MODEL_SEMAPHORE_LIMIT = None


class StructuredRunnable(Protocol):
    """Minimal protocol required to invoke a structured model."""

    def invoke(self, input: object) -> object: ...


class ModelContextLimitError(ValueError):
    """Raised when a request exceeds the configured token budget."""


class GeminiStructuredOutputError(ValueError):
    """Raised when Gemini returns an empty or schema-incompatible structured response."""


def safe_provider_error_metadata(
    error: BaseException,
) -> tuple[int | None, str | None]:
    """Extract only bounded status/code metadata from a provider error chain."""

    status_code: int | None = None
    provider_code: str | None = None
    for candidate in _error_chain(error):
        if isinstance(candidate, RateLimitCoordinationError):
            return 503, "RATE_COORDINATION_ERROR"
        candidate_status = getattr(candidate, "status_code", None)
        if (
            status_code is None
            and isinstance(candidate_status, int)
            and not isinstance(candidate_status, bool)
        ):
            status_code = candidate_status

        raw_code = getattr(candidate, "code", None)
        if (
            status_code is None
            and isinstance(raw_code, int)
            and not isinstance(raw_code, bool)
        ):
            status_code = raw_code

        if not isinstance(raw_code, str):
            raw_code = getattr(candidate, "status", None)

        if not isinstance(raw_code, str):
            body = getattr(candidate, "body", None) or getattr(candidate, "details", None)
            if isinstance(body, dict):
                provider_error = body.get("error")
                if isinstance(provider_error, dict):
                    err_code = provider_error.get("code")
                    if (
                        status_code is None
                        and isinstance(err_code, int)
                        and not isinstance(err_code, bool)
                    ):
                        status_code = err_code
                    raw_code = (
                        err_code
                        if isinstance(err_code, str)
                        else provider_error.get("status")
                    )
                elif provider_error is None:
                    err_code = body.get("code")
                    if (
                        status_code is None
                        and isinstance(err_code, int)
                        and not isinstance(err_code, bool)
                    ):
                        status_code = err_code
                    raw_code = (
                        err_code
                        if isinstance(err_code, str)
                        else body.get("status")
                    )
        if (
            provider_code is None
            and isinstance(raw_code, str)
            and _SAFE_PROVIDER_CODE.fullmatch(raw_code)
        ):
            provider_code = raw_code

    return status_code, provider_code


def provider_failure_category(error: BaseException) -> str:
    """Return a safe, stable category without exposing provider messages."""

    for candidate in _error_chain(error):
        if isinstance(candidate, RateLimitCoordinationError):
            return "rate_coordination_unavailable"

    status_code, provider_code = safe_provider_error_metadata(error)

    # Context length check from error messages/classes
    for candidate in _error_chain(error):
        if isinstance(candidate, ModelContextLimitError):
            return "context_length_exceeded"
        msg = str(candidate).casefold()
        if (
            "context_length" in msg
            or "context length" in msg
            or "maximum context" in msg
            or "context_window" in msg
        ):
            return "context_length_exceeded"

    # HTTP 413: payload/context overflow (must NOT map to rate_limited)
    if status_code == 413:
        return "payload_too_large"

    if provider_code in {
        "context_length_exceeded",
        "context_window_exceeded",
        "model_context_window_exceeded",
    }:
        return "context_length_exceeded"

    if provider_code in {
        "insufficient_quota",
        "quota_exceeded",
        "billing_hard_limit",
    }:
        return "quota_exceeded"

    if status_code == 429:
        if provider_code in {
            "insufficient_quota",
            "quota_exceeded",
            "billing_hard_limit",
        }:
            return "quota_exceeded"
        return "rate_limited"

    if provider_code in {"rate_limit_exceeded", "RESOURCE_EXHAUSTED"}:
        return "rate_limited"
    if provider_code == "tool_use_failed":
        return "malformed_response"

    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        if provider_code in {"insufficient_quota", "quota_exceeded"}:
            return "quota_exceeded"
        return "permission_error"
    if status_code in {408, 504}:
        return "provider_timeout"
    if status_code in {400, 422}:
        return "invalid_request"
    if status_code is not None and status_code >= 500:
        return "provider_unavailable"

    for candidate in _error_chain(error):
        if isinstance(candidate, GeminiStructuredOutputError):
            return "malformed_response"
        error_name = type(candidate).__name__.casefold()
        if isinstance(candidate, TimeoutError) or "timeout" in error_name:
            return "provider_timeout"
        if isinstance(candidate, (ConnectionError, OSError)) or "connection" in error_name:
            return "provider_unavailable"
        if "validation" in error_name:
            return "schema_validation_error"
        if "jsondecode" in error_name or "malformed" in error_name or "outputparser" in error_name:
            return "malformed_response"

    return "unknown_provider_error"


def safe_retry_metadata(error: BaseException) -> dict[str, object]:
    """Return bounded retry metadata without exposing arbitrary headers."""

    status_code, _ = safe_provider_error_metadata(error)
    header_keys: tuple[str, ...] = (
        (
            "retry-after",
            "x-ratelimit-reset-tokens",
            "x-ratelimit-reset-requests",
        )
        if status_code == 429
        else ("retry-after",)
    )

    for candidate in _error_chain(error):
        response = getattr(candidate, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            headers = getattr(candidate, "headers", None)
        if headers is None:
            continue

        metadata: dict[str, object] = {}
        lowered_headers: dict[str, object] = (
            {str(k).casefold(): v for k, v in headers.items()}
            if hasattr(headers, "items")
            else {}
        )
        retry_header = lowered_headers.get("x-should-retry") or headers.get("x-should-retry")
        if isinstance(retry_header, str) and retry_header.strip().casefold() in {"true", "false"}:
            metadata["provider_retry_hint"] = retry_header.strip().casefold() == "true"

        parsed_delays: list[float] = []
        for header_key in header_keys:
            raw_val = lowered_headers.get(header_key)
            if raw_val is None:
                raw_val = headers.get(header_key)
            if raw_val is not None:
                delay = _retry_after_seconds(str(raw_val))
                if delay is not None:
                    parsed_delays.append(delay)
        if parsed_delays:
            metadata["retry_after_seconds"] = max(parsed_delays)
        return metadata
    return {}


def _request_token_count(
    *,
    messages: list[tuple[str, str]],
    output_schema: type[BaseModel],
) -> tuple[int, int, int]:
    settings = get_settings()
    encoding = tiktoken.get_encoding(settings.groq_tokenizer_encoding)
    message_text = "\n".join(
        f"{role}\n{content}" for role, content in messages
    )
    schema_text = output_schema.model_json_schema()
    schema_json = json.dumps(
        schema_text,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    prompt_tokens = (
        len(encoding.encode(message_text, disallowed_special=()))
        + PROTOCOL_OVERHEAD_TOKENS
    )
    schema_tokens = len(encoding.encode(schema_json, disallowed_special=()))
    request_bytes = len(message_text.encode("utf-8")) + len(
        schema_json.encode("utf-8")
    )
    return prompt_tokens, schema_tokens, request_bytes


def _retry_after_seconds(value: str) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None

    val = value.strip().casefold()
    try:
        seconds = float(val)
        if 0 <= seconds <= 3600:
            return seconds
    except ValueError:
        pass

    if val.endswith("ms"):
        try:
            ms = float(val[:-2].strip())
            return min(max(ms / 1000.0, 0.0), 3600.0)
        except ValueError:
            pass

    # Support compound formats like '1m26.4s', '2m', '45s', '1m 30s'
    duration_match = re.fullmatch(
        r"(?:(\d+(?:\.\d+)?)\s*m(?:in(?:utes?)?)?)?\s*(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?)?",
        val,
    )
    if duration_match and (duration_match.group(1) or duration_match.group(2)):
        minutes = float(duration_match.group(1) or 0.0)
        seconds = float(duration_match.group(2) or 0.0)
        total_seconds = minutes * 60.0 + seconds
        if 0 <= total_seconds <= 3600:
            return total_seconds

    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = (retry_at - datetime.now(UTC)).total_seconds()
        if 0 <= seconds <= 3600:
            return seconds
    except (TypeError, ValueError, OverflowError):
        pass

    return None


def _retry_delay(error: BaseException, attempt: int) -> float:
    try:
        settings = get_settings()
        max_delay = getattr(settings, "groq_max_retry_delay_seconds", _MAX_RETRY_DELAY_SECONDS)
    except Exception:
        max_delay = _MAX_RETRY_DELAY_SECONDS

    metadata = safe_retry_metadata(error)
    retry_after = metadata.get("retry_after_seconds")
    if isinstance(retry_after, (int, float)):
        # Provider explicitly instructed when to retry; do not cap below provider reset window
        provider_bound = max(
            getattr(settings, "groq_timeout_seconds", 60.0),
            getattr(settings, "groq_max_retry_delay_seconds", 60.0),
            65.0,
        )
        return min(max(float(retry_after), 0.05), provider_bound)

    backoff = 0.5 * (2**attempt)
    jitter = random.uniform(0.0, min(backoff, 0.5))
    return min(max_delay, backoff + jitter)


def _is_retryable(error: BaseException) -> bool:
    metadata = safe_retry_metadata(error)
    if metadata.get("provider_retry_hint") is False:
        return False

    cat = provider_failure_category(error)
    if cat == "quota_exceeded":
        return False
    if cat in {"rate_limited", "provider_timeout", "provider_unavailable", "malformed_response"}:
        return True

    status_code, _ = safe_provider_error_metadata(error)
    if status_code in {408, 409, 429}:
        return True
    if status_code is not None and status_code >= 500:
        return True
    return False


def _has_gemini_fallback(settings: object) -> bool:
    """Return True when a non-empty GEMINI_API_KEY is configured."""
    raw_key = getattr(settings, "gemini_api_key", None)
    if raw_key is None:
        return False
    secret_val = (
        raw_key.get_secret_value()
        if hasattr(raw_key, "get_secret_value")
        else str(raw_key)
    )
    return bool(secret_val.strip())


def _resolve_fallback_target(
    settings: object,
) -> tuple[str, str, object] | None:
    """Resolve the active fallback provider, model name, and model instance if configured."""
    if _has_gemini_fallback(settings):
        gemini_model = (getattr(settings, "gemini_model", None) or "gemini-3.8-flash").strip()
        gemini_chat = get_gemini_chat_model()
        if gemini_chat is not None:
            return ("gemini", gemini_model, gemini_chat)

    fallback_model_name = (getattr(settings, "groq_fallback_model", None) or "").strip()
    if fallback_model_name and fallback_model_name != getattr(settings, "groq_model", ""):
        groq_fb = get_fallback_chat_model()
        if groq_fb is not None:
            return ("groq", fallback_model_name, groq_fb)

    return None


def invoke_structured(
    runnable: StructuredRunnable,
    *,
    messages: list[tuple[str, str]],
    output_schema: type[BaseModel],
    stage: str,
) -> object:
    """Token-bound and invoke a structured request with safe transient retries and Gemini fallback."""

    settings = get_settings()
    primary_model_name = getattr(settings, "groq_model", "openai/gpt-oss-120b")
    prompt_tokens, schema_tokens, request_bytes = _request_token_count(
        messages=messages,
        output_schema=output_schema,
    )
    estimated_input_tokens = prompt_tokens + schema_tokens

    # 1. Enforce canonical stage-specific input token budget
    budget_mgr = get_token_budget_manager()
    stage_allocation = budget_mgr.get_allocation(stage)
    stage_budget = stage_allocation.max_input_tokens
    if estimated_input_tokens > stage_budget:
        diag = {
            "stage": stage,
            "provider": "groq",
            "model": primary_model_name,
            "primary_provider": "groq",
            "primary_model": primary_model_name,
            "fallback_used": False,
            "estimated_input_tokens": estimated_input_tokens,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.0,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "payload_too_large",
            "status_code": 413,
            "provider_code": "STAGE_BUDGET_EXCEEDED",
        }
        last_invocation_diagnostic_ctx.set(diag)
        raise ModelContextLimitError(
            f"The model request for {stage} ({estimated_input_tokens} estimated tokens) "
            f"exceeds the configured stage input budget of {stage_budget} tokens."
        )

    # 2. Secondary global ceiling check
    if estimated_input_tokens > settings.groq_max_input_tokens:
        diag = {
            "stage": stage,
            "provider": "groq",
            "model": primary_model_name,
            "primary_provider": "groq",
            "primary_model": primary_model_name,
            "fallback_used": False,
            "estimated_input_tokens": estimated_input_tokens,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.0,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "payload_too_large",
            "status_code": 413,
            "provider_code": "GLOBAL_BUDGET_EXCEEDED",
        }
        last_invocation_diagnostic_ctx.set(diag)
        raise ModelContextLimitError(
            f"The model request exceeds the configured global input token budget "
            f"({estimated_input_tokens} > {settings.groq_max_input_tokens})."
        )

    inv_id = investigation_id_ctx.get()
    logger.info(
        "AI request prepared (investigation_id=%s, stage=%s, provider=groq, model=%s, "
        "prompt_tokens=%d, schema_tokens=%d, estimated_request_bytes=%d).",
        inv_id,
        stage,
        primary_model_name,
        prompt_tokens,
        schema_tokens,
        request_bytes,
    )

    # 3. Coordinate rate coordination across distributed processes (PostgreSQL)
    try:
        get_shared_rate_limiter().acquire_permit(
            estimated_tokens=estimated_input_tokens,
            stage=stage,
        )
    except RateLimitCoordinationError:
        diag = {
            "stage": stage,
            "provider": "groq",
            "model": primary_model_name,
            "primary_provider": "groq",
            "primary_model": primary_model_name,
            "fallback_used": False,
            "estimated_input_tokens": estimated_input_tokens,
            "actual_prompt_tokens": None,
            "actual_completion_tokens": None,
            "execution_duration": 0.0,
            "retry_attempts": 0,
            "status": "unavailable",
            "category": "rate_coordination_unavailable",
            "status_code": 503,
            "provider_code": "RATE_COORDINATION_ERROR",
        }
        last_invocation_diagnostic_ctx.set(diag)
        raise

    _active_semaphore = get_model_semaphore()
    if not _active_semaphore.acquire(
        timeout=settings.groq_timeout_seconds,
    ):
        raise TimeoutError("The model request concurrency limit was reached.")

    max_retries = getattr(settings, "groq_max_retries", 3)
    max_attempts = 1 + max_retries
    has_gemini_fb = _has_gemini_fallback(settings)

    usage_callback = UsageCaptureCallbackHandler()
    t_start = time.perf_counter()

    try:
        for attempt in range(max_attempts):
            try:
                try:
                    result = runnable.invoke(messages, config={"callbacks": [usage_callback]})
                except TypeError:
                    result = runnable.invoke(messages)

                duration = time.perf_counter() - t_start
                last_invocation_diagnostic_ctx.set({
                    "stage": stage,
                    "provider": "groq",
                    "model": primary_model_name,
                    "primary_provider": "groq",
                    "primary_model": primary_model_name,
                    "fallback_used": False,
                    "estimated_input_tokens": estimated_input_tokens,
                    "actual_prompt_tokens": usage_callback.prompt_tokens,
                    "actual_completion_tokens": usage_callback.completion_tokens,
                    "execution_duration": round(duration, 3),
                    "retry_attempts": attempt,
                    "status": "completed",
                    "category": None,
                    "status_code": 200,
                    "provider_code": None,
                })
                return result
            except Exception as exc:
                cat = provider_failure_category(exc)
                status_code, provider_code = safe_provider_error_metadata(exc)
                retry_meta = safe_retry_metadata(exc)
                retry_after = retry_meta.get("retry_after_seconds")
                if (
                    status_code == 429
                    and isinstance(retry_after, (int, float))
                    and retry_after > 0
                    and retry_meta.get("provider_retry_hint") is not False
                    and cat != "quota_exceeded"
                ):
                    get_shared_rate_limiter().record_provider_cooldown(float(retry_after))

                # When Gemini fallback is configured and Groq hits 429 / rate_limited / quota_exceeded,
                # transition immediately to Gemini fallback without sleeping on Groq's rate-limit window.
                immediate_gemini_failover = has_gemini_fb and (
                    status_code == 429 or cat in {"rate_limited", "quota_exceeded"}
                )

                if (
                    immediate_gemini_failover
                    or attempt + 1 >= max_attempts
                    or not _is_retryable(exc)
                ):
                    fallback_target = _resolve_fallback_target(settings)
                    fallback_provider_name: str | None = None
                    fallback_attempted: str | None = None
                    fallback_failure_category: str | None = None
                    fallback_status_code: int | None = None
                    fallback_provider_code: str | None = None

                    should_attempt_fallback = False
                    if fallback_target is not None:
                        fb_prov, fb_mod, _ = fallback_target
                        if fb_prov == "gemini":
                            # Gemini secondary provider handles 429, quota exhaustion, repeated malformed responses, or provider failure
                            should_attempt_fallback = True
                        else:
                            should_attempt_fallback = (
                                status_code == 429
                                or cat in {"rate_limited", "quota_exceeded", "malformed_response"}
                                or provider_code == "tool_use_failed"
                            )

                    if fallback_target is not None and should_attempt_fallback:
                        fallback_provider_name, fallback_model_name, fallback_chat = fallback_target
                        fallback_attempted = fallback_model_name
                        try:
                            logger.warning(
                                "Primary model failed (investigation_id=%s, stage=%s, primary_provider=groq, "
                                "primary_model=%s, category=%s, status_code=%s, provider_code=%s); "
                                "attempting fallback provider=%s, model=%s.",
                                inv_id,
                                stage,
                                primary_model_name,
                                cat,
                                status_code,
                                provider_code,
                                fallback_provider_name,
                                fallback_model_name,
                            )
                            try:
                                fallback_runnable = fallback_chat.with_structured_output(
                                    output_schema,
                                    method="function_calling",
                                )
                            except TypeError:
                                fallback_runnable = fallback_chat.with_structured_output(
                                    output_schema,
                                )
                            try:
                                fb_result = fallback_runnable.invoke(
                                    messages,
                                    config={"callbacks": [usage_callback]},
                                )
                            except TypeError:
                                fb_result = fallback_runnable.invoke(messages)

                            if isinstance(fb_result, dict):
                                fb_result = output_schema.model_validate(fb_result)
                            elif isinstance(fb_result, BaseModel):
                                if not isinstance(fb_result, output_schema):
                                    fb_result = output_schema.model_validate(
                                        fb_result.model_dump(mode="python")
                                    )
                            else:
                                raise GeminiStructuredOutputError(
                                    f"Fallback model returned invalid type {type(fb_result).__name__}."
                                )

                            duration = time.perf_counter() - t_start
                            logger.info(
                                "Fallback LLM request succeeded (investigation_id=%s, stage=%s, "
                                "provider=%s, model=%s, duration=%.3fs).",
                                inv_id,
                                stage,
                                fallback_provider_name,
                                fallback_model_name,
                                duration,
                            )
                            last_invocation_diagnostic_ctx.set({
                                "stage": stage,
                                "provider": fallback_provider_name,
                                "model": fallback_model_name,
                                "primary_provider": "groq",
                                "primary_model": primary_model_name,
                                "fallback_used": True,
                                "fallback_provider": fallback_provider_name,
                                "fallback_model_used": fallback_model_name,
                                "estimated_input_tokens": estimated_input_tokens,
                                "actual_prompt_tokens": usage_callback.prompt_tokens,
                                "actual_completion_tokens": usage_callback.completion_tokens,
                                "execution_duration": round(duration, 3),
                                "retry_attempts": attempt + 1,
                                "status": "completed",
                                "category": None,
                                "status_code": 200,
                                "provider_code": None,
                                "primary_model_failure_category": cat,
                                "primary_model_status_code": status_code,
                                "primary_model_provider_code": provider_code,
                                "retry_after_seconds": retry_meta.get("retry_after_seconds"),
                                "provider_retry_hint": retry_meta.get("provider_retry_hint"),
                            })
                            return fb_result
                        except Exception as fb_exc:
                            fallback_failure_category = provider_failure_category(fb_exc)
                            fallback_status_code, fallback_provider_code = (
                                safe_provider_error_metadata(fb_exc)
                            )
                            logger.warning(
                                "Configured fallback model failed (investigation_id=%s, stage=%s, "
                                "fallback_provider=%s, fallback_model=%s, category=%s, "
                                "status_code=%s, provider_code=%s, error_type=%s).",
                                inv_id,
                                stage,
                                fallback_provider_name,
                                fallback_model_name,
                                fallback_failure_category,
                                fallback_status_code,
                                fallback_provider_code,
                                type(fb_exc).__name__,
                            )

                    duration = time.perf_counter() - t_start
                    diag_payload: dict[str, object] = {
                        "stage": stage,
                        "provider": "groq",
                        "model": primary_model_name,
                        "primary_provider": "groq",
                        "primary_model": primary_model_name,
                        "fallback_used": False,
                        "estimated_input_tokens": estimated_input_tokens,
                        "actual_prompt_tokens": None,
                        "actual_completion_tokens": None,
                        "execution_duration": round(duration, 3),
                        "retry_attempts": attempt,
                        "status": "unavailable",
                        "category": cat,
                        "status_code": status_code,
                        "provider_code": provider_code,
                        "provider_retry_hint": retry_meta.get("provider_retry_hint"),
                        "retry_after_seconds": retry_meta.get("retry_after_seconds"),
                    }
                    if fallback_attempted is not None:
                        diag_payload["fallback_provider"] = fallback_provider_name
                        diag_payload["fallback_model_attempted"] = fallback_attempted
                        diag_payload["fallback_failure_category"] = fallback_failure_category
                        diag_payload["fallback_status_code"] = fallback_status_code
                        diag_payload["fallback_provider_code"] = fallback_provider_code
                    last_invocation_diagnostic_ctx.set(diag_payload)
                    logger.error(
                        "Fatal LLM provider error (investigation_id=%s, stage=%s, provider=groq, "
                        "model=%s, attempt=%d/%d, category=%s, status_code=%s, provider_code=%s, "
                        "fallback_attempted=%s, fallback_failure_category=%s): %s",
                        inv_id,
                        stage,
                        primary_model_name,
                        attempt + 1,
                        max_attempts,
                        cat,
                        status_code,
                        provider_code,
                        fallback_attempted,
                        fallback_failure_category,
                        type(exc).__name__,
                    )
                    raise
                delay = _retry_delay(exc, attempt)
                logger.warning(
                    "Transient AI request failure (investigation_id=%s, stage=%s, provider=groq, "
                    "model=%s, attempt=%d/%d, delay=%.2fs, category=%s, status_code=%s, provider_code=%s); retrying.",
                    inv_id,
                    stage,
                    primary_model_name,
                    attempt + 1,
                    max_attempts,
                    delay,
                    cat,
                    status_code,
                    provider_code,
                )
                time.sleep(delay)
    finally:
        _active_semaphore.release()

    raise RuntimeError("The model request ended without a result.")


def _error_chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _validate_max_output_tokens(max_tokens: int) -> int:
    """Validate configured output token limit against provider bounds."""
    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens < 128
        or max_tokens > 8192
    ):
        raise ValueError(
            "GROQ_MAX_OUTPUT_TOKENS must be an integer between 128 and 8192."
        )
    return max_tokens


def _format_gemini_messages(
    messages: object,
) -> tuple[str | None, list[genai_types.Content]]:
    """Convert (role, text) tuples or message objects into Gemini system_instruction and contents."""
    system_parts: list[str] = []
    contents: list[genai_types.Content] = []

    if isinstance(messages, str):
        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text=messages)],
            )
        )
        return None, contents

    if isinstance(messages, (list, tuple)):
        for item in messages:
            role = "user"
            text = ""
            if isinstance(item, (list, tuple)) and len(item) == 2:
                role = str(item[0]).strip().casefold()
                text = str(item[1])
            elif hasattr(item, "content"):
                role = str(getattr(item, "type", getattr(item, "role", "user"))).strip().casefold()
                text = str(getattr(item, "content", ""))
            elif isinstance(item, dict):
                role = str(item.get("role", "user")).strip().casefold()
                text = str(item.get("content", ""))
            else:
                text = str(item)

            if role == "system":
                if text.strip():
                    system_parts.append(text.strip())
            else:
                gemini_role = "model" if role in {"assistant", "ai", "model"} else "user"
                contents.append(
                    genai_types.Content(
                        role=gemini_role,
                        parts=[genai_types.Part.from_text(text=text)],
                    )
                )

    if not contents:
        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part.from_text(text="")],
            )
        )

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


def _sanitize_gemini_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively remove additionalProperties keys rejected by the Gemini API."""
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if isinstance(value, dict):
            cleaned[key] = _sanitize_gemini_json_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _sanitize_gemini_json_schema(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned


class GeminiStructuredRunnable:
    """Structured-output and function-calling runnable backed by the official Google GenAI SDK."""

    def __init__(
        self,
        *,
        client: genai.Client,
        model: str,
        output_schema: type[BaseModel],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: float = 60.0,
        method: str | None = "function_calling",
    ) -> None:
        self.client = client
        self.model = model
        self.output_schema = output_schema
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.method = method

    def invoke(
        self,
        input: object,
        config: dict[str, Any] | None = None,
    ) -> BaseModel:
        system_instruction, contents = _format_gemini_messages(input)
        raw_schema = self.output_schema.model_json_schema()
        response_schema: Any = (
            _sanitize_gemini_json_schema(raw_schema)
            if "additionalProperties" in json.dumps(raw_schema)
            else self.output_schema
        )
        config_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
            "response_mime_type": "application/json",
            "response_schema": response_schema,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if self.timeout and self.timeout > 0:
            config_kwargs["http_options"] = genai_types.HttpOptions(
                timeout=max(1000, int(self.timeout * 1000))
            )

        gen_config = genai_types.GenerateContentConfig(**config_kwargs)
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=gen_config,
        )

        # Capture token usage metadata for stage diagnostics
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta is not None and isinstance(config, dict):
            callbacks = config.get("callbacks") or []
            if isinstance(callbacks, list):
                for cb in callbacks:
                    if isinstance(cb, UsageCaptureCallbackHandler):
                        cb.prompt_tokens = getattr(usage_meta, "prompt_token_count", None)
                        cb.completion_tokens = getattr(usage_meta, "candidates_token_count", None)
                        cb.total_tokens = getattr(usage_meta, "total_token_count", None)

        # 1. Check SDK-parsed object
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, self.output_schema):
            try:
                return self.output_schema.model_validate(parsed.model_dump(mode="python"))
            except ValidationError as val_exc:
                raise GeminiStructuredOutputError(
                    f"Gemini parsed response failed {self.output_schema.__name__} validation."
                ) from val_exc
        if isinstance(parsed, BaseModel):
            try:
                return self.output_schema.model_validate(parsed.model_dump(mode="python"))
            except ValidationError as val_exc:
                raise GeminiStructuredOutputError(
                    f"Gemini parsed model failed {self.output_schema.__name__} validation."
                ) from val_exc
        if isinstance(parsed, dict):
            try:
                return self.output_schema.model_validate(parsed)
            except ValidationError as val_exc:
                raise GeminiStructuredOutputError(
                    f"Gemini parsed dict failed {self.output_schema.__name__} validation."
                ) from val_exc

        # 2. Check function_calls if tool-calling response was returned
        function_calls = getattr(response, "function_calls", None)
        if isinstance(function_calls, list) and function_calls:
            first_call = function_calls[0]
            call_args = getattr(first_call, "args", None)
            if isinstance(call_args, dict):
                try:
                    return self.output_schema.model_validate(call_args)
                except ValidationError as val_exc:
                    raise GeminiStructuredOutputError(
                        f"Gemini tool call arguments failed {self.output_schema.__name__} validation."
                    ) from val_exc

        # 3. Parse JSON text
        raw_text = getattr(response, "text", None)
        if isinstance(raw_text, str) and raw_text.strip():
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(
                    r"^```(?:json)?\s*|\s*```$",
                    "",
                    cleaned,
                    flags=re.IGNORECASE,
                ).strip()
            try:
                return self.output_schema.model_validate_json(cleaned)
            except Exception as val_exc:
                raise GeminiStructuredOutputError(
                    f"Gemini JSON text failed {self.output_schema.__name__} validation."
                ) from val_exc

        raise GeminiStructuredOutputError(
            f"Gemini returned an empty structured response for {self.output_schema.__name__}."
        )


class GeminiToolRunnable:
    """Tool-calling runnable backed by the official Google GenAI SDK."""

    def __init__(
        self,
        *,
        client: genai.Client,
        model: str,
        tools: Sequence[Any],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: float = 60.0,
    ) -> None:
        self.client = client
        self.model = model
        self.tools = list(tools)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def invoke(
        self,
        input: object,
        config: dict[str, Any] | None = None,
    ) -> object:
        system_instruction, contents = _format_gemini_messages(input)
        declarations: list[genai_types.FunctionDeclaration] = []
        schema_map: dict[str, type[BaseModel]] = {}

        for tool in self.tools:
            if isinstance(tool, type) and issubclass(tool, BaseModel):
                schema_map[tool.__name__] = tool
                declarations.append(
                    genai_types.FunctionDeclaration(
                        name=tool.__name__,
                        description=tool.__doc__ or f"Structured tool for {tool.__name__}",
                        parameters=_sanitize_gemini_json_schema(tool.model_json_schema()),
                    )
                )

        config_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if declarations:
            config_kwargs["tools"] = [genai_types.Tool(function_declarations=declarations)]
            config_kwargs["tool_config"] = genai_types.ToolConfig(
                function_calling_config=genai_types.FunctionCallingConfig(mode="ANY")
            )
        else:
            config_kwargs["tools"] = self.tools

        gen_config = genai_types.GenerateContentConfig(**config_kwargs)
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=gen_config,
        )
        function_calls = getattr(response, "function_calls", None)
        if isinstance(function_calls, list) and function_calls:
            fc = function_calls[0]
            name = getattr(fc, "name", "")
            args = getattr(fc, "args", None)
            if name in schema_map and isinstance(args, dict):
                return schema_map[name].model_validate(args)
            return {"name": name, "args": args}
        return response


class GeminiChatModel:
    """Official Google GenAI SDK chat model adapter matching ClaimSage's LLM interface."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_tokens: int = 4096,
        client: genai.Client | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._client = client or genai.Client(api_key=api_key)

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: str | None = "function_calling",
        **kwargs: Any,
    ) -> GeminiStructuredRunnable:
        return GeminiStructuredRunnable(
            client=self._client,
            model=self.model,
            output_schema=schema,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            method=method,
        )

    def bind_tools(
        self,
        tools: Sequence[Any],
        **kwargs: Any,
    ) -> GeminiToolRunnable:
        return GeminiToolRunnable(
            client=self._client,
            model=self.model,
            tools=tools,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )


@lru_cache(maxsize=1)
def get_chat_model() -> ChatGroq:
    """Create and cache the configured primary Groq chat model."""
    settings = get_settings()

    if settings.groq_api_key is None:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add it to the backend environment."
        )

    api_key = settings.groq_api_key.get_secret_value().strip()

    if not api_key:
        raise RuntimeError("GROQ_API_KEY is empty.")

    effective_max_tokens = _validate_max_output_tokens(
        settings.groq_max_output_tokens
    )
    model = ChatGroq(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        api_key=api_key,
        timeout=settings.groq_timeout_seconds,
        max_retries=0,
        max_tokens=effective_max_tokens,
    )
    logger.info(
        "Initialized Groq chat model (model=%s, max_tokens=%d, api_key_present=true).",
        settings.groq_model,
        effective_max_tokens,
    )
    return model


def get_gemini_chat_model() -> GeminiChatModel | None:
    """Create the configured secondary fallback Google Gemini chat model when GEMINI_API_KEY is set."""
    settings = get_settings()
    raw_key = getattr(settings, "gemini_api_key", None)
    if raw_key is None:
        return None
    api_key = (
        raw_key.get_secret_value().strip()
        if hasattr(raw_key, "get_secret_value")
        else str(raw_key).strip()
    )
    if not api_key:
        return None

    gemini_model = (getattr(settings, "gemini_model", None) or "gemini-3.8-flash").strip()
    if not gemini_model:
        return None

    effective_max_tokens = _validate_max_output_tokens(
        getattr(settings, "groq_max_output_tokens", 4096)
    )
    model = GeminiChatModel(
        model=gemini_model,
        api_key=api_key,
        temperature=getattr(settings, "llm_temperature", 0.0),
        timeout=getattr(settings, "groq_timeout_seconds", 60.0),
        max_tokens=effective_max_tokens,
    )
    logger.info(
        "Initialized Gemini fallback chat model (provider=gemini, model=%s, max_tokens=%d, api_key_present=true).",
        gemini_model,
        effective_max_tokens,
    )
    return model


def get_fallback_chat_model() -> ChatGroq | None:
    """Create the explicitly configured fallback Groq chat model when set."""
    settings = get_settings()
    fallback_model = (getattr(settings, "groq_fallback_model", None) or "").strip()
    if not fallback_model or fallback_model == settings.groq_model:
        return None
    if settings.groq_api_key is None:
        return None
    api_key = settings.groq_api_key.get_secret_value().strip()
    if not api_key:
        return None
    effective_max_tokens = _validate_max_output_tokens(
        settings.groq_max_output_tokens
    )
    return ChatGroq(
        model=fallback_model,
        temperature=settings.llm_temperature,
        api_key=api_key,
        timeout=settings.groq_timeout_seconds,
        max_retries=0,
        max_tokens=effective_max_tokens,
    )


def quote_matches_evidence(quote_text: str, evidence_text: str) -> bool:
    """Check if quote_text matches evidence_text verbatim, normalized, or via ordered ellipsis segments."""
    if not isinstance(quote_text, str) or not isinstance(evidence_text, str):
        return False
    if quote_text in evidence_text:
        return True

    def _norm(s: str) -> str:
        return " ".join(
            s.casefold()
            .replace("“", '"')
            .replace("”", '"')
            .replace("„", '"')
            .replace("‟", '"')
            .replace("“", '"')
            .replace("”", '"')
            .replace("‘", "'")
            .replace("’", "'")
            .replace("‚", "'")
            .replace("‛", "'")
            .replace("‘", "'")
            .replace("’", "'")
            .replace("`", "'")
            .replace("´", "'")
            .replace("‐", "-")
            .replace("‑", "-")  # non-breaking hyphen
            .replace("‒", "-")
            .replace("–", "-")
            .replace("—", "-")
            .replace("−", "-")  # minus sign
            .replace("–", "-")
            .replace("—", "-")
            .replace(" ", " ")  # non-breaking space
            .replace(" ", " ")  # narrow no-break space
            .replace(" ", " ")  # thin space
            .replace(" ", " ")
            .replace(" ", " ")
            .replace("​", "")   # zero-width space
            .replace("­", "")   # soft hyphen
            .split()
        )

    norm_quote = _norm(quote_text).strip("\"' ")
    norm_evidence = _norm(evidence_text)
    if not norm_quote:
        return False
    if norm_quote in norm_evidence:
        return True
    trimmed_quote = norm_quote.strip("\"' .,;:!?")
    if trimmed_quote and trimmed_quote in norm_evidence:
        return True

    segments = [
        seg.strip("\"' .,;:!? ")
        for seg in re.split(r"\.{3,}|…", norm_quote)
        if len(seg.strip("\"' .,;:!? ")) >= 4
    ]
    if not segments:
        return False

    last_idx = 0
    for seg in segments:
        idx = norm_evidence.find(seg, last_idx)
        if idx == -1:
            return False
        last_idx = idx + len(seg)
    return True
