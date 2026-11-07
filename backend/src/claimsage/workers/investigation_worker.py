"""Durable PostgreSQL worker for ClaimSage multi-agent investigations."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

from claimsage.agents.graph import InvestigationState, run_investigation
from claimsage.core.observability import investigation_id_ctx, worker_id_ctx
from claimsage.db.models import Claim, InvestigationRun
from claimsage.db.session import SessionLocal
from claimsage.services.investigation_persistence import (
    fail_investigation,
    finish_investigation,
    persist_progress,
)
from claimsage.services.notifications import (
    NotificationEvent,
    dispatch_notification,
    enqueue_notification,
)

logger = logging.getLogger("claimsage.worker")


class WorkerFencedError(RuntimeError):
    """Raised when another worker has superseded ownership of the active investigation."""


class _HeartbeatRunner:
    """Background heartbeat to refresh leases during long-running LangGraph executions."""

    def __init__(
        self,
        worker: InvestigationWorker,
        investigation_id: UUID,
        interval_seconds: float,
    ) -> None:
        self.worker = worker
        self.investigation_id = investigation_id
        self.interval = interval_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{investigation_id}",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                with self.worker.session_factory() as session:
                    now = datetime.now(UTC)
                    stmt = (
                        update(InvestigationRun)
                        .where(
                            InvestigationRun.id == self.investigation_id,
                            InvestigationRun.worker_id == self.worker.worker_id,
                            InvestigationRun.status == "running",
                        )
                        .values(
                            lease_expires_at=now + timedelta(seconds=self.worker.lease_duration_seconds)
                        )
                    )
                    res = session.execute(stmt)
                    session.commit()
                    if res.rowcount == 0:
                        logger.warning(
                            "Worker %s was fenced during execution of investigation %s.",
                            self.worker.worker_id,
                            self.investigation_id,
                        )
                        self.worker._fenced_investigations.add(self.investigation_id)
                        break
            except Exception as exc:
                logger.warning(
                    "Heartbeat update failed for investigation %s: %s",
                    self.investigation_id,
                    exc,
                )


class InvestigationWorker:
    """PostgreSQL-backed worker using an at-least-once execution model with idempotent side effects.

    Queue claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` with explicit lease durations.
    Active ownership is renewed via background heartbeats and guarded by optimistic worker fencing.
    If an external LLM call finishes but the worker abruptly crashes before persistence, the job
    lease expires naturally and will be safely reclaimed by another worker for re-execution.
    """

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        session_factory: Callable[[], Session] = SessionLocal,
        poll_interval_seconds: float = 2.0,
        lease_duration_seconds: int = 120,
    ) -> None:
        self.worker_id = worker_id or (
            f"worker-{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:6]}"
        )
        self.session_factory = session_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.lease_duration_seconds = lease_duration_seconds
        self._stopping = False
        self._current_investigation_id: UUID | None = None
        self._fenced_investigations: set[UUID] = set()

    def request_stop(self, *args: Any) -> None:
        """Signal the worker to complete its active job and shutdown cleanly."""
        logger.info("Worker %s received termination signal. Shutting down gracefully...", self.worker_id)
        self._stopping = True

    def setup_signal_handlers(self) -> None:
        """Register OS signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self.request_stop)
            signal.signal(signal.SIGTERM, self.request_stop)
        except (ValueError, AttributeError):
            # Signals might not be interceptable in certain non-main thread contexts
            pass

    def check_readiness(self) -> dict[str, Any]:
        """Verify database connectivity and investigation queue table availability.

        Raises an exception if the database cannot be contacted or the
        investigation queue table does not exist.
        """
        with self.session_factory() as session:
            current_db = session.scalar(text("SELECT current_database()"))
            stmt = select(func.count(InvestigationRun.id)).where(InvestigationRun.status == "running")
            active_jobs = session.scalar(stmt)
            return {
                "status": "ready",
                "worker_id": self.worker_id,
                "database": current_db,
                "queue_table": "accessible",
                "active_running_jobs": int(active_jobs or 0),
            }

    def claim_next_job(self, session: Session) -> UUID | None:
        """Atomically claim one eligible investigation job using FOR UPDATE SKIP LOCKED."""
        now = datetime.now(UTC)
        statement = (
            select(InvestigationRun)
            .where(
                InvestigationRun.status == "running",
                or_(
                    InvestigationRun.current_stage == "queued",
                    and_(
                        InvestigationRun.lease_expires_at.is_not(None),
                        InvestigationRun.lease_expires_at < now,
                        InvestigationRun.attempt_count < InvestigationRun.max_attempts,
                    ),
                ),
            )
            .order_by(InvestigationRun.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        job = session.scalar(statement)
        if job is None:
            session.rollback()
            return None

        job.worker_id = self.worker_id
        job.attempt_count += 1
        job.current_stage = "starting"
        job.lease_expires_at = now + timedelta(seconds=self.lease_duration_seconds)
        job_id = job.id
        session.commit()

        logger.info(
            "Worker %s claimed investigation %s (attempt %d/%d).",
            self.worker_id,
            job_id,
            job.attempt_count,
            job.max_attempts,
        )
        return job_id

    def reap_expired_jobs(self, session: Session) -> int:
        """Mark abandoned jobs with exceeded retry counts as failed."""
        now = datetime.now(UTC)
        statement = (
            select(InvestigationRun)
            .where(
                InvestigationRun.status == "running",
                InvestigationRun.lease_expires_at.is_not(None),
                InvestigationRun.lease_expires_at < now,
                InvestigationRun.attempt_count >= InvestigationRun.max_attempts,
            )
            .with_for_update(skip_locked=True)
        )
        expired_jobs = session.scalars(statement).all()
        count = len(expired_jobs)
        for job in expired_jobs:
            logger.warning(
                "Investigation %s exceeded maximum retries (%d). Marking failed.",
                job.id,
                job.attempt_count,
            )
            job.status = "failed"
            job.failure_type = "MaxRetriesExceeded"
            job.current_stage = None
            job.worker_id = None
            job.lease_expires_at = None
            job.completed_at = now
        if count > 0:
            session.commit()
        else:
            session.rollback()
        return count

    def execute_job(self, investigation_id: UUID) -> None:
        """Execute an investigation in an isolated session with progress heartbeats."""
        self._current_investigation_id = investigation_id
        self._fenced_investigations.discard(investigation_id)

        # Set observability context
        worker_token = worker_id_ctx.set(self.worker_id)
        inv_token = investigation_id_ctx.set(str(investigation_id))

        # Start background heartbeat thread (interval = lease_duration / 3)
        heartbeat_interval = max(5.0, self.lease_duration_seconds / 3.0)
        heartbeat = _HeartbeatRunner(self, investigation_id, heartbeat_interval)
        heartbeat.start()

        try:
            with self.session_factory() as worker_session:
                investigation = worker_session.get(InvestigationRun, investigation_id)
                if investigation is None:
                    logger.error("Investigation %s was not found for execution.", investigation_id)
                    return

                # Verify this worker still owns the investigation
                if investigation_id in self._fenced_investigations or (
                    isinstance(investigation.worker_id, str)
                    and investigation.worker_id != self.worker_id
                ):
                    logger.warning(
                        "Worker %s does not own investigation %s (current owner: %s). Aborting execution.",
                        self.worker_id,
                        investigation_id,
                        investigation.worker_id,
                    )
                    return

                if not isinstance(investigation.worker_id, str):
                    investigation.worker_id = self.worker_id

                claim = worker_session.get(Claim, investigation.claim_id)
                if claim is None:
                    logger.error("Claim %s not found for investigation %s.", investigation.claim_id, investigation_id)
                    fail_investigation(
                        worker_session,
                        investigation=investigation,
                        failure_type="ClaimNotFoundError",
                    )
                    return

                # Resolve repair estimate document ID from model attribute or state snapshot
                repair_estimate_doc_id = investigation.repair_estimate_document_id
                if repair_estimate_doc_id is None and isinstance(investigation.state_snapshot, dict):
                    raw_doc_id = investigation.state_snapshot.get("repair_estimate_document_id")
                    if raw_doc_id:
                        try:
                            repair_estimate_doc_id = UUID(str(raw_doc_id))
                        except ValueError:
                            pass

                last_state: InvestigationState | None = None

                def save_progress(node_name: str, state: InvestigationState) -> None:
                    nonlocal last_state
                    last_state = state

                    # Check fencing before persisting progress
                    if investigation.worker_id != self.worker_id or investigation_id in self._fenced_investigations:
                        raise WorkerFencedError(
                            f"Worker {self.worker_id} was fenced for investigation {investigation_id}."
                        )

                    persist_progress(
                        worker_session,
                        investigation=investigation,
                        stage=node_name,
                        state=state,
                        lease_seconds=self.lease_duration_seconds,
                    )

                try:
                    run_kwargs: dict[str, Any] = {
                        "session": worker_session,
                        "employee_id": investigation.initiated_by_employee_id,
                        "claim_id": investigation.claim_id,
                        "task": investigation.task,
                        "repair_estimate_document_id": repair_estimate_doc_id,
                        "on_progress": save_progress,
                    }
                    if isinstance(investigation.state_snapshot, dict) and isinstance(
                        investigation.state_snapshot.get("result"), dict
                    ):
                        run_kwargs["resume_state"] = investigation.state_snapshot
                    outcome = run_investigation(**run_kwargs)

                    # Check fencing before committing final outcome
                    if investigation.worker_id != self.worker_id or investigation_id in self._fenced_investigations:
                        raise WorkerFencedError(
                            f"Worker {self.worker_id} was fenced for investigation {investigation_id}."
                        )

                    finish_investigation(
                        worker_session,
                        investigation=investigation,
                        state=outcome,
                    )
                    if outcome.get("error") is None and isinstance(outcome.get("result"), dict):
                        recipient_id = claim.assigned_employee_id or investigation.initiated_by_employee_id
                        self._dispatch_review_notification(
                            session=worker_session,
                            event=NotificationEvent.INVESTIGATION_COMPLETED,
                            recipient_employee_id=recipient_id,
                            investigation_id=investigation.id,
                            claim_id=claim.id,
                        )
                        if outcome["result"].get("human_review_required") is True:
                            self._dispatch_review_notification(
                                session=worker_session,
                                event=NotificationEvent.HUMAN_REVIEW_REQUIRED,
                                recipient_employee_id=recipient_id,
                                investigation_id=investigation.id,
                                claim_id=claim.id,
                            )
                    logger.info(
                        "Investigation %s finished successfully with status %s.",
                        investigation_id,
                        investigation.status,
                    )
                except WorkerFencedError:
                    logger.warning(
                        "Worker %s aborted execution of investigation %s because it was fenced.",
                        self.worker_id,
                        investigation_id,
                    )
                except Exception as exc:
                    if investigation_id in self._fenced_investigations:
                        logger.warning(
                            "Worker %s encountered %s but was already fenced for %s; skipping state modification.",
                            self.worker_id,
                            type(exc).__name__,
                            investigation_id,
                        )
                        return

                    logger.warning(
                        "Investigation %s execution failed (error_type=%s, attempt=%d/%d).",
                        investigation_id,
                        type(exc).__name__,
                        investigation.attempt_count,
                        investigation.max_attempts,
                    )

                    # Bounded retry: if retries remain and error is not a fatal domain defect, release lease
                    is_fatal_error = type(exc).__name__ in {"ClaimNotFoundError", "PolicyNotFoundError"}
                    attempt_count = (
                        investigation.attempt_count
                        if isinstance(getattr(investigation, "attempt_count", None), int)
                        else 1
                    )
                    max_attempts = (
                        investigation.max_attempts
                        if isinstance(getattr(investigation, "max_attempts", None), int)
                        else 1
                    )
                    if attempt_count < max_attempts and not is_fatal_error:
                        logger.info(
                            "Investigation %s eligible for retry (attempt %d/%d). Releasing lease.",
                            investigation_id,
                            investigation.attempt_count,
                            investigation.max_attempts,
                        )
                        investigation.worker_id = None
                        investigation.lease_expires_at = None
                        investigation.current_stage = "queued"
                        worker_session.commit()
                    else:
                        try:
                            fail_investigation(
                                worker_session,
                                investigation=investigation,
                                failure_type=type(exc).__name__,
                                state=last_state,
                            )
                        except Exception as persist_err:
                            logger.error(
                                "Failed to persist failure state for investigation %s: %s",
                                investigation_id,
                                persist_err,
                            )
        finally:
            heartbeat.stop()
            self._current_investigation_id = None
            worker_id_ctx.reset(worker_token)
            investigation_id_ctx.reset(inv_token)

    def _dispatch_review_notification(
        self,
        *,
        session: Session,
        event: NotificationEvent,
        recipient_employee_id: UUID,
        investigation_id: UUID,
        claim_id: UUID,
    ) -> None:
        try:
            notification_id = enqueue_notification(
                session,
                event=event,
                recipient_employee_id=recipient_employee_id,
                resource_id=investigation_id,
                application_path=f"/claims/{claim_id}",
            )
            session.commit()
            dispatch_notification(notification_id, session_factory=self.session_factory)
        except Exception as exc:
            logger.warning(
                "Notification dispatch failed (event=%s, error_type=%s).",
                event.value,
                type(exc).__name__,
            )

    def run_once(self) -> bool:
        """Poll and execute at most one job. Returns True if a job was processed."""
        with self.session_factory() as session:
            self.reap_expired_jobs(session)
            job_id = self.claim_next_job(session)

        if job_id is not None:
            self.execute_job(job_id)
            return True
        return False

    def start(self) -> None:
        """Start continuous job polling loop until stopped."""
        self.setup_signal_handlers()
        logger.info(
            "Investigation worker %s started. Polling every %.1fs (lease: %ds)...",
            self.worker_id,
            self.poll_interval_seconds,
            self.lease_duration_seconds,
        )
        while not self._stopping:
            try:
                processed = self.run_once()
                if not processed and not self._stopping:
                    time.sleep(self.poll_interval_seconds)
            except Exception as exc:
                logger.error("Unexpected error in worker polling loop: %s", exc)
                if not self._stopping:
                    time.sleep(self.poll_interval_seconds)
        logger.info("Investigation worker %s stopped.", self.worker_id)
