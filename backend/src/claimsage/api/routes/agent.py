"""Authenticated ClaimSage investigation endpoint."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.agents.graph import run_investigation
from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import Claim, Employee, InvestigationRun
from claimsage.db.session import SessionLocal, get_db
from claimsage.rag.evidence_retrieval_service import (
    resolve_repair_estimate_document_id,
)
from claimsage.schemas.agent import (
    InvestigationRequest,
    InvestigationResponse,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)
from claimsage.services.investigation_persistence import (
    create_investigation_run,
    fail_investigation,
    finish_investigation,
    is_investigation_complete,
    persist_progress,
)
from claimsage.services.notifications import (
    NotificationEvent,
    dispatch_notification,
    enqueue_notification,
)
from claimsage.workers.investigation_worker import InvestigationWorker

router = APIRouter(prefix="/agent", tags=["AI Agent"])
logger = logging.getLogger(__name__)


def _queue_review_notifications(
    *,
    session: Session,
    background_tasks: BackgroundTasks | None = None,
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
    except Exception as exc:
        session.rollback()
        logger.warning(
            "Notification enqueue failed (event=%s, error_type=%s).",
            event.value,
            type(exc).__name__,
        )
        return
    try:
        if background_tasks is not None:
            background_tasks.add_task(dispatch_notification, notification_id)
        else:
            dispatch_notification(notification_id)
    except Exception as exc:
        logger.warning(
            "Notification dispatch scheduling failed "
            "(event=%s, error_type=%s).",
            event.value,
            type(exc).__name__,
        )


def _run_investigation_background(
    investigation_id: UUID,
    claim_id: UUID | None = None,
    employee_id: UUID | None = None,
    task: str | None = None,
    repair_estimate_document_id: UUID | None = None,
) -> None:
    """Execution helper delegating to InvestigationWorker."""
    worker = InvestigationWorker(session_factory=SessionLocal)
    worker.execute_job(investigation_id)


@router.post(
    "/investigations",
    response_model=InvestigationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def investigate_claim(
    request: InvestigationRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> InvestigationResponse:
    """Validate claim access, persist a durable queued investigation job, and return 202."""

    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=request.claim_id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

    # Check for duplicate execution: prevent multiple concurrent runs on the same claim
    active_run = session.scalar(
        select(InvestigationRun)
        .where(
            InvestigationRun.claim_id == claim.id,
            InvestigationRun.status == "running",
        )
        .order_by(InvestigationRun.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if active_run is not None:
        now = datetime.now(UTC)
        is_stale = False
        if active_run.lease_expires_at is not None:
            # Lease expired and unrenewed beyond buffer
            if now > active_run.lease_expires_at + timedelta(minutes=5):
                is_stale = True
        else:
            # Check updated_at heartbeat rather than created_at
            run_updated = (
                active_run.updated_at.replace(tzinfo=UTC)
                if active_run.updated_at.tzinfo is None
                else active_run.updated_at
            )
            if now - run_updated > timedelta(minutes=15):
                is_stale = True

        if is_stale:
            active_run.status = "failed"
            active_run.failure_type = "InvestigationTimeout"
            active_run.current_stage = None
            active_run.lease_expires_at = None
            session.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"An investigation is already in progress for this claim "
                    f"(ID: {active_run.id})."
                ),
            )

    resolved_estimate_document_id = request.repair_estimate_document_id
    if (
        resolved_estimate_document_id is None
        and isinstance(getattr(claim, "claim_type", None), str)
        and claim.claim_type.strip().lower() in {"auto", "motor"}
    ):
        resolved_estimate_document_id = resolve_repair_estimate_document_id(
            session,
            employee_id=employee.id,
            claim_id=claim.id,
        )

    investigation = create_investigation_run(
        session,
        claim=claim,
        employee_id=employee.id,
        task=request.task,
        repair_estimate_document_id=resolved_estimate_document_id,
    )

    return InvestigationResponse(
        investigation_id=investigation.id,
        execution_status="running",
        status="running",
        claim_facts=None,
        result=None,
        error=None,
    )
