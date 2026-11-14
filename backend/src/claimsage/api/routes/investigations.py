"""Authorized read and human-review APIs for persisted investigations."""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import (
    AuditEvent,
    CustomerEmail,
    Employee,
    EmployeeRole,
    InvestigationReview,
    InvestigationRun,
    NotificationDelivery,
)
from claimsage.db.session import get_db
from claimsage.schemas.agent import InvestigationResponse
from claimsage.schemas.human_review import (
    FindingEditRequest,
    FindingEditResponse,
    InvestigationReviewRequest,
)
from claimsage.schemas.investigation import (
    EvidenceSufficiency,
    InvestigationDetail,
    InvestigationFindingResponse,
    InvestigationReportResponse,
    InvestigationReviewResponse,
    InvestigationSummary,
    NotificationDeliveryResponse,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)
from claimsage.services.human_review import (
    HumanReviewError,
    create_finding_edit,
    list_finding_edits,
    record_human_review,
)
from claimsage.services.notifications import (
    NotificationEvent,
    dispatch_notification,
    enqueue_notification,
)

router = APIRouter(prefix="/agent", tags=["Investigations"])
logger = logging.getLogger(__name__)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Investigation not found or access denied.",
    )


def _get_authorized_investigation(
    session: Session,
    *,
    employee: Employee,
    investigation_id: UUID,
    load_details: bool = False,
) -> InvestigationRun:
    statement = select(InvestigationRun).where(
        InvestigationRun.id == investigation_id
    )
    if load_details:
        statement = statement.options(
            selectinload(InvestigationRun.findings),
            selectinload(InvestigationRun.report),
        )
    investigation = session.scalar(statement)
    if investigation is None:
        raise _not_found()
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=investigation.claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None
    return investigation


def _summary(investigation: InvestigationRun) -> InvestigationSummary:
    report_data = (
        investigation.report.report_data
        if investigation.report is not None
        else None
    )
    report_outcome = (
        report_data.get("overall_status")
        if isinstance(report_data, dict)
        else None
    )
    evidence_sufficiency: EvidenceSufficiency | None = {
        "completed": "sufficient_for_analysis",
        "insufficient_evidence": "insufficient_evidence",
        "incomplete": "undetermined",
    }.get(report_outcome)
    return InvestigationSummary(
        id=investigation.id,
        claim_id=investigation.claim_id,
        claim_domain=investigation.claim_domain,
        status=investigation.status,
        current_stage=investigation.current_stage,
        human_review_status=investigation.human_review_status,
        report_status=(
            investigation.report.status
            if investigation.report is not None
            else None
        ),
        evidence_sufficiency=evidence_sufficiency,
        created_at=investigation.created_at,
        updated_at=investigation.updated_at,
        completed_at=investigation.completed_at,
    )


@router.get(
    "/claims/{claim_id}/investigations",
    response_model=list[InvestigationSummary],
)
def list_claim_investigations(
    claim_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[InvestigationSummary]:
    """List investigations only after authorizing the requested claim."""
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    investigations = session.scalars(
        select(InvestigationRun)
        .options(selectinload(InvestigationRun.report))
        .where(InvestigationRun.claim_id == claim_id)
        .order_by(InvestigationRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_summary(item) for item in investigations]


@router.get(
    "/investigations/{investigation_id}",
    response_model=InvestigationDetail,
)
def get_investigation(
    investigation_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> InvestigationDetail:
    """Retrieve a run and findings after rechecking claim-level access."""
    investigation = _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
        load_details=True,
    )
    return InvestigationDetail(
        **_summary(investigation).model_dump(),
        task=investigation.task,
        failure_type=investigation.failure_type,
        state_snapshot=investigation.state_snapshot,
        findings=[
            InvestigationFindingResponse.model_validate(finding)
            for finding in investigation.findings
        ],
    )


@router.get(
    "/investigations/{investigation_id}/report",
    response_model=InvestigationReportResponse,
)
def get_investigation_report(
    investigation_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> InvestigationReportResponse:
    """Retrieve a report, including qualified partial/unavailable outcomes."""
    investigation = _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
        load_details=True,
    )
    report = investigation.report
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation report is not available yet.",
        )
    return InvestigationReportResponse(
        id=report.id,
        investigation_id=report.investigation_id,
        status=report.status,
        report_data=report.report_data,
        limitations=report.limitations,
        human_review_required=True,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@router.get(
    "/investigations/{investigation_id}/result",
    response_model=InvestigationResponse,
)
def get_investigation_result(
    investigation_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> InvestigationResponse:
    """Retrieve investigation execution status and completed results."""
    investigation = _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
        load_details=True,
    )
    snapshot = investigation.state_snapshot or {}
    result = snapshot.get("result") if isinstance(snapshot, dict) else None
    claim_facts = snapshot.get("claim_facts") if isinstance(snapshot, dict) else None
    error = snapshot.get("error") if isinstance(snapshot, dict) else None
    if investigation.status == "failed" and not error:
        error = f"Investigation failed: {investigation.failure_type or 'Unknown error'}"

    execution_status = (
        "completed"
        if investigation.status == "completed"
        else "failed"
        if investigation.status == "failed"
        else "running"
        if investigation.status == "running"
        else "incomplete"
    )

    return InvestigationResponse(
        investigation_id=investigation.id,
        execution_status=execution_status,
        status=investigation.status,
        claim_facts=claim_facts,
        result=result,
        error=error,
    )


@router.get(
    "/investigations/{investigation_id}/notifications",
    response_model=list[NotificationDeliveryResponse],
)
def list_investigation_notifications(
    investigation_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[NotificationDeliveryResponse]:
    """Return safe email delivery states and customer notification drafts for this investigation."""
    investigation = _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
    )
    delivery_stmt = select(NotificationDelivery).where(
        NotificationDelivery.resource_id == str(investigation.id)
    )
    if employee.role != EmployeeRole.ADMIN:
        delivery_stmt = delivery_stmt.where(
            NotificationDelivery.recipient_employee_id == employee.id
        )
    deliveries = session.scalars(
        delivery_stmt.order_by(NotificationDelivery.created_at.desc())
    ).all()

    items: list[NotificationDeliveryResponse] = [
        NotificationDeliveryResponse(
            id=delivery.id,
            event_type=delivery.event_type,
            status=delivery.status,
            attempt_count=delivery.attempt_count,
            last_error_type=delivery.last_error_type,
            created_at=delivery.created_at,
            updated_at=delivery.updated_at,
            delivered_at=delivery.delivered_at,
            is_draft=False,
        )
        for delivery in deliveries
    ]

    # Include customer email drafts attached to this investigation (or claim with matching evidence request)
    emails = session.scalars(
        select(CustomerEmail)
        .where(
            CustomerEmail.claim_id == investigation.claim_id,
            (CustomerEmail.investigation_id == investigation.id) | (CustomerEmail.investigation_id.is_(None)),
        )
        .order_by(CustomerEmail.created_at.desc())
    ).all()

    for email in emails:
        status_val = "drafted" if email.status == "drafted" else (
            email.status if email.status in ("pending", "sending", "delivered", "sandboxed", "failed") else "pending"
        )
        event_type_val = email.event_type if email.event_type in (
            "claim_received", "investigation_completed", "human_review_required", "additional_evidence_required", "review_completed"
        ) else "additional_evidence_required"

        items.append(
            NotificationDeliveryResponse(
                id=email.id,
                event_type=event_type_val,
                status=status_val,
                attempt_count=email.attempt_count or 0,
                last_error_type=email.last_error_type,
                created_at=email.created_at,
                updated_at=email.updated_at,
                delivered_at=email.sent_at,
                recipient_email=email.recipient_email,
                recipient_name=email.recipient_name,
                subject=email.subject,
                message=email.body_text,
                secure_upload_url=email.secure_upload_url,
                is_draft=(email.status == "drafted"),
            )
        )

    return items


@router.post(
    "/investigations/{investigation_id}/reviews",
    response_model=InvestigationReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_investigation_review(
    investigation_id: UUID,
    request: InvestigationReviewRequest,
    background_tasks: BackgroundTasks,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> InvestigationReviewResponse:
    """Append an authorized human review status; this endpoint cannot decide a claim."""
    if employee.role != EmployeeRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators are authorized to submit human review decisions.",
        )
    investigation = _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
    )

    try:
        review, _email_draft = record_human_review(
            session,
            investigation=investigation,
            employee=employee,
            request=request,
        )
        session.commit()
        session.refresh(review)
    except HumanReviewError as exc:
        session.rollback()
        msg = str(exc)
        if "must finish before" in msg or "already approved" in msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=msg,
            ) from None
        if "not authorized" in msg or "access denied" in msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=msg,
            ) from None
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        ) from None
    except IntegrityError as exc:
        session.rollback()
        logger.warning("Integrity error during review submission: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The review submission violates database integrity constraints.",
        ) from None
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("Database error during review submission: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Investigation review could not be saved.",
        ) from None

    if request.decision in {"reviewed", "needs_follow_up", "needs_additional_documents"}:
        event = (
            NotificationEvent.REVIEW_COMPLETED
            if request.decision == "reviewed"
            else NotificationEvent.ADDITIONAL_EVIDENCE_REQUIRED
        )
        recipient_id = investigation.initiated_by_employee_id
        try:
            notification_id = enqueue_notification(
                session,
                event=event,
                recipient_employee_id=recipient_id,
                resource_id=investigation.id,
                application_path=f"/claims/{investigation.claim_id}",
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning(
                "Review notification enqueue failed (event=%s, error_type=%s).",
                event.value,
                type(exc).__name__,
            )
        else:
            try:
                background_tasks.add_task(
                    dispatch_notification,
                    notification_id,
                )
            except Exception as exc:
                logger.warning(
                    "Review notification scheduling failed "
                    "(event=%s, error_type=%s).",
                    event.value,
                    type(exc).__name__,
                )

    return InvestigationReviewResponse(
        id=review.id,
        investigation_id=review.investigation_id,
        reviewer_employee_id=employee.id,
        reviewer_name=employee.display_name,
        decision=review.decision,
        notes=review.notes,
        created_at=review.created_at,
    )


@router.get(
    "/investigations/{investigation_id}/reviews",
    response_model=list[InvestigationReviewResponse],
)
def list_investigation_reviews(
    investigation_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[InvestigationReviewResponse]:
    """Retrieve attributed review history after claim-level authorization."""
    investigation = _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
    )
    rows = session.execute(
        select(InvestigationReview, Employee.display_name)
        .join(Employee, Employee.id == InvestigationReview.reviewer_employee_id)
        .where(
            InvestigationReview.investigation_id == investigation.id
        )
        .order_by(InvestigationReview.created_at.desc())
    ).all()
    return [
        InvestigationReviewResponse(
            id=review.id,
            investigation_id=review.investigation_id,
            reviewer_employee_id=review.reviewer_employee_id,
            reviewer_name=reviewer_name,
            decision=review.decision,
            notes=review.notes,
            created_at=review.created_at,
        )
        for review, reviewer_name in rows
    ]


@router.post(
    "/investigations/{investigation_id}/findings/{finding_id}/edits",
    response_model=FindingEditResponse,
    status_code=status.HTTP_201_CREATED,
)
def edit_investigation_finding(
    investigation_id: UUID,
    finding_id: UUID,
    request: FindingEditRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> FindingEditResponse:
    """Record a versioned human modification to an AI finding without modifying the original."""
    _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
    )
    try:
        edit = create_finding_edit(
            session,
            finding_id=finding_id,
            employee=employee,
            request=request,
        )
        session.commit()
        session.refresh(edit)
        return FindingEditResponse(
            id=edit.id,
            finding_id=edit.finding_id,
            investigation_id=edit.investigation_id,
            editor_employee_id=edit.editor_employee_id,
            editor_name=employee.display_name,
            original_data=edit.original_data,
            edited_data=edit.edited_data,
            reason=edit.reason,
            created_at=edit.created_at,
        )
    except HumanReviewError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None


@router.get(
    "/investigations/{investigation_id}/findings/{finding_id}/edits",
    response_model=list[FindingEditResponse],
)
def list_finding_edits_endpoint(
    investigation_id: UUID,
    finding_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[FindingEditResponse]:
    """List versioned revision history for a specific finding."""
    _get_authorized_investigation(
        session,
        employee=employee,
        investigation_id=investigation_id,
    )
    try:
        edits = list_finding_edits(
            session,
            finding_id=finding_id,
            employee=employee,
        )
        return [
            FindingEditResponse(
                id=edit.id,
                finding_id=edit.finding_id,
                investigation_id=edit.investigation_id,
                editor_employee_id=edit.editor_employee_id,
                editor_name=edit.editor_name,
                original_data=edit.original_data,
                edited_data=edit.edited_data,
                reason=edit.reason,
                created_at=edit.created_at,
            )
            for edit in edits
        ]
    except HumanReviewError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
