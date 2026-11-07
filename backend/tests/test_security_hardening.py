"""Tests for security hardening, sensitive data redaction, rate limiting, and observability."""

import json
import logging
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import Response

from claimsage.core.config import Settings
from claimsage.core.observability import (
    CorrelationIdMiddleware,
    StructuredJsonFormatter,
    correlation_id_ctx,
    investigation_id_ctx,
    worker_id_ctx,
)
from claimsage.core.rate_limit import InMemoryRateLimiter
from claimsage.services.audit import sanitize_metadata


def test_audit_sensitive_metadata_redaction() -> None:
    """sanitize_metadata redacts passwords, tokens, SSNs, and credit cards."""
    dirty_payload = {
        "user_id": str(uuid4()),
        "password": "super-secret-password-123",
        "api_key": "groq-key-abc",
        "credit_card": "4111-2222-3333-4444",
        "notes": "Patient SSN is 123-45-6789 and payment card is 5555 4444 3333 2222 on file.",
    }

    clean = sanitize_metadata(dirty_payload)

    assert clean["password"] == "[REDACTED]"
    assert clean["api_key"] == "[REDACTED]"
    assert clean["credit_card"] == "[REDACTED]"
    assert "123-45-6789" not in clean["notes"]
    assert "[REDACTED_SSN]" in clean["notes"]
    assert "5555 4444 3333 2222" not in clean["notes"]
    assert "[REDACTED_CARD]" in clean["notes"]


def test_insecure_jwt_secret_rejected_in_production() -> None:
    """Production mode must reject known default or weak JWT secrets."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://user:pass@prod-db:5432/claimsage_prod",
            jwt_secret_key="test-jwt-secret-key-that-is-at-least-32-bytes-long",
            groq_api_key="gsk-valid-key-example-123",
            storage_backend="s3",
            storage_use_ssl=True,
            storage_endpoint_url="https://s3.amazonaws.com",
            storage_access_key="valid-access-key",
            storage_secret_key="valid-secret-key",
            _env_file=None,
        )
    assert "insecure default JWT_SECRET_KEY" in str(exc_info.value)


def test_rate_limiter_enforces_sliding_window() -> None:
    """InMemoryRateLimiter rejects requests exceeding threshold within window."""
    limiter = InMemoryRateLimiter(default_limit=3, window_seconds=60)
    client_id = "client-ip-1.2.3.4"

    # First 3 requests allowed
    assert limiter.is_allowed(client_id)[0] is True
    assert limiter.is_allowed(client_id)[0] is True
    assert limiter.is_allowed(client_id)[0] is True

    # 4th request disallowed
    allowed, retry_after = limiter.is_allowed(client_id)
    assert allowed is False
    assert retry_after > 0


def test_rate_limiter_memory_sweep() -> None:
    """Inactive client buckets are pruned during sweep to prevent memory leak."""
    limiter = InMemoryRateLimiter(default_limit=5, window_seconds=1)
    limiter.is_allowed("ephemeral-client-1")
    assert "ephemeral-client-1" in limiter._hits

    # Simulate passage of time past window_seconds
    limiter._sweep_expired(window_start=1e12)
    assert "ephemeral-client-1" not in limiter._hits


def test_structured_json_formatter_injects_context() -> None:
    """StructuredJsonFormatter includes correlation, worker, and investigation IDs."""
    formatter = StructuredJsonFormatter()
    logger = logging.getLogger("test_obs")

    record = logger.makeRecord(
        name="test_obs",
        level=logging.INFO,
        fn="test_file.py",
        lno=42,
        msg="Executing step",
        args=(),
        exc_info=None,
    )

    test_cid = "req-12345"
    test_wid = "worker-abc"
    test_inv = "inv-67890"

    t1 = correlation_id_ctx.set(test_cid)
    t2 = worker_id_ctx.set(test_wid)
    t3 = investigation_id_ctx.set(test_inv)

    try:
        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["level"] == "INFO"
        assert data["logger"] == "test_obs"
        assert data["message"] == "Executing step"
        assert data["correlation_id"] == test_cid
        assert data["worker_id"] == test_wid
        assert data["investigation_id"] == test_inv
        assert "timestamp" in data
    finally:
        correlation_id_ctx.reset(t1)
        worker_id_ctx.reset(t2)
        investigation_id_ctx.reset(t3)
