"""Shared PostgreSQL-coordinated rate limiter for ClaimSage LLM requests.

Coordinates token consumption and request timing across backend and worker
processes using PostgreSQL advisory locks and existing audit_events records.
Does not require Redis, Celery, or database migrations.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from claimsage.core.config import get_settings
from claimsage.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Dedicated 64-bit advisory lock key for rate limit coordination
GROQ_RATE_LIMIT_LOCK_ID = 82947101

# Default settings
DEFAULT_TPM_LIMIT = 4500  # Conservative ceiling below provider TPM + completion budget
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_ACQUIRE_TIMEOUT = 10.0


class RateLimitCoordinationError(RuntimeError):
    """Raised when shared PostgreSQL rate coordination fails."""
    pass


class SharedRateLimiter:
    """Coordinates LLM request pacing across distributed processes via PostgreSQL."""

    def __init__(
        self,
        *,
        tpm_limit: int = DEFAULT_TPM_LIMIT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        lock_id: int = GROQ_RATE_LIMIT_LOCK_ID,
    ) -> None:
        self.tpm_limit = tpm_limit
        self.window_seconds = window_seconds
        self.lock_id = lock_id

    def acquire_permit(
        self,
        *,
        estimated_tokens: int,
        stage: str,
        session_factory: Any = SessionLocal,
    ) -> float:
        """Coordinate rate limit across processes and sleep if needed.

        Acquires an advisory lock briefly inside a transaction to inspect the
        shared rolling token usage and reserve tokens. Releases the database
        connection BEFORE sleeping and before provider execution.

        Returns the seconds waited.
        """
        settings = get_settings()
        if settings.app_env == "test" and not getattr(settings, "force_rate_limiter_in_test", False):
            return 0.0

        wait_seconds = 0.0
        now = datetime.now(UTC)

        try:
            with session_factory() as db:
                with db.begin():
                    # 1. Acquire transaction-level advisory lock (auto-releases at commit/rollback)
                    db.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_id)"),
                        {"lock_id": self.lock_id},
                    )

                    # 2. Check for active provider cooldown (e.g. from 429 Retry-After)
                    cooldown_res = db.execute(
                        text("""
                            SELECT event_metadata->>'cooldown_until' as cd
                            FROM audit_events
                            WHERE action = 'ai_provider_cooldown'
                              AND created_at >= :recent
                            ORDER BY created_at DESC
                            LIMIT 1
                        """),
                        {"recent": now - timedelta(minutes=5)},
                    ).first()

                    cooldown_wait = 0.0
                    if cooldown_res and cooldown_res[0]:
                        try:
                            cooldown_dt = datetime.fromisoformat(cooldown_res[0])
                            if cooldown_dt.tzinfo is None:
                                cooldown_dt = cooldown_dt.replace(tzinfo=UTC)
                            diff = (cooldown_dt - now).total_seconds()
                            if diff > 0:
                                cooldown_wait = min(diff, 120.0)
                        except Exception:
                            pass

                    # 3. Sum active token reservations within rolling window
                    window_start = now - timedelta(seconds=self.window_seconds)
                    recent_cutoff = now - timedelta(seconds=self.window_seconds * 2)
                    recent_reservations = db.execute(
                        text("""
                            SELECT
                                COALESCE((event_metadata->>'projected_at')::timestamptz, created_at) as effective_at,
                                (event_metadata->>'estimated_tokens')::int as tokens
                            FROM audit_events
                            WHERE action = 'ai_token_reservation'
                              AND created_at >= :recent_cutoff
                              AND COALESCE((event_metadata->>'projected_at')::timestamptz, created_at) >= :window_start
                            ORDER BY effective_at ASC
                        """),
                        {"recent_cutoff": recent_cutoff, "window_start": window_start},
                    ).fetchall()

                    current_tokens = sum(r[1] for r in recent_reservations if r[1] is not None)

                    if cooldown_wait > 0:
                        wait_seconds = cooldown_wait
                    elif current_tokens + estimated_tokens > self.tpm_limit:
                        # Need to wait until enough oldest reservations age out
                        tokens_to_free = (current_tokens + estimated_tokens) - self.tpm_limit
                        freed = 0
                        oldest_age_needed = None
                        for r_effective_at, r_tokens in recent_reservations:
                            if r_tokens:
                                freed += r_tokens
                                oldest_age_needed = r_effective_at
                                if freed >= tokens_to_free:
                                    break

                        if oldest_age_needed:
                            if oldest_age_needed.tzinfo is None:
                                oldest_age_needed = oldest_age_needed.replace(tzinfo=UTC)
                            elapsed = (now - oldest_age_needed).total_seconds()
                            wait_seconds = max(0.5, self.window_seconds - elapsed + 0.5)
                        else:
                            wait_seconds = 5.0
                    else:
                        wait_seconds = 0.0

                    # 4. Insert new reservation (preserves actual insert time in created_at,
                    #    stores projected execution time in event_metadata)
                    projected_at = now + timedelta(seconds=wait_seconds)
                    db.execute(
                        text("""
                            INSERT INTO audit_events (
                                id, actor_type, event_category, action, outcome,
                                resource_type, details, event_metadata, created_at
                            ) VALUES (
                                :id, 'system', 'ai_rate_limiter', 'ai_token_reservation', 'success',
                                'groq_tpm', :details, :metadata, :created_at
                            )
                        """),
                        {
                            "id": uuid.uuid4(),
                            "details": f"Stage {stage} reserved {estimated_tokens} tokens",
                            "metadata": json.dumps({
                                "estimated_tokens": estimated_tokens,
                                "stage": stage,
                                "projected_at": projected_at.isoformat(),
                            }),
                            "created_at": now,
                        },
                    )

            # Transaction is committed and closed here! Lock is released.

        except Exception as exc:
            logger.error(
                "Shared rate coordination failed for stage %s: %s",
                stage,
                exc,
            )
            raise RateLimitCoordinationError(
                "Unable to acquire a shared rate-limit permit from PostgreSQL. "
                "The request was safely aborted to prevent provider quota exhaustion."
            ) from None

        # Sleep outside of any database transaction or connection
        if wait_seconds > 0:
            logger.info(
                "Shared rate coordinator pacing stage %s for %.2fs (estimated_tokens=%d)...",
                stage,
                wait_seconds,
                estimated_tokens,
            )
            time.sleep(wait_seconds)

        return wait_seconds

    def record_provider_cooldown(
        self,
        seconds: float,
        *,
        session_factory: Any = SessionLocal,
    ) -> None:
        """Record an explicit provider cooldown (e.g. from Retry-After)."""
        if seconds <= 0:
            return
        now = datetime.now(UTC)
        cooldown_until = now + timedelta(seconds=seconds)
        try:
            with session_factory() as db:
                db.execute(
                    text("""
                        INSERT INTO audit_events (
                            id, actor_type, event_category, action, outcome,
                            resource_type, details, event_metadata, created_at
                        ) VALUES (
                            :id, 'system', 'ai_rate_limiter', 'ai_provider_cooldown', 'success',
                            'groq_tpm', :details, :metadata, :created_at
                        )
                    """),
                    {
                        "id": uuid.uuid4(),
                        "details": f"Provider requested cooldown for {seconds:.2f}s",
                        "metadata": json.dumps({
                            "cooldown_until": cooldown_until.isoformat(),
                            "retry_after_seconds": seconds,
                        }),
                        "created_at": now,
                    },
                )
                db.commit()
                logger.info(
                    "Shared rate coordinator recorded provider cooldown until %s (%.1fs).",
                    cooldown_until.isoformat(),
                    seconds,
                )
        except Exception as exc:
            logger.warning("Failed to record provider cooldown: %s", exc)


_shared_rate_limiter: SharedRateLimiter | None = None


def get_shared_rate_limiter() -> SharedRateLimiter:
    """Return singleton instance of SharedRateLimiter."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:
        _shared_rate_limiter = SharedRateLimiter()
    return _shared_rate_limiter
