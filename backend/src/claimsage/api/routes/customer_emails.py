"""API endpoints for managing customer email communications and human review approval gates."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import Claim, CustomerEmail, Employee, EmployeeRole, NotificationDelivery
from claimsage.db.session import get_db
from claimsage.schemas.customer_emails import (
    CustomerEmailApprovalRequest,
    CustomerEmailDraftRequest,
    CustomerEmailResponse,
    CustomerEmailUpdateRequest,
    EmailFollowUpListItem,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)
from claimsage.services.customer_emails import (
    approve_email,
    check_overdue_reminders,
    create_email_draft,
    dispatch_approved_email,
    update_email_draft,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims", tags=["Customer Emails"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Claim or email not found, or access denied.",
    )


@router.get(
    "/emails",
    response_model=list[EmailFollowUpListItem],
)
def list_all_email_follow_ups(
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[EmailFollowUpListItem]:
    """List customer email drafts and notification deliveries across authorized claims."""
    stmt = (
        select(CustomerEmail)
        .join(Claim, CustomerEmail.claim_id == Claim.id)
        .options(selectinload(CustomerEmail.claim))
    )

    if employee.role == EmployeeRole.ADMIN:
        pass
    elif employee.role == EmployeeRole.CLAIMS_ADJUSTER:
        stmt = stmt.where(Claim.assigned_employee_id == employee.id)
    elif employee.role in {EmployeeRole.TEAM_LEAD, EmployeeRole.POLICY_SPECIALIST}:
        if employee.team_id:
            stmt = stmt.where(Claim.team_id == employee.team_id)
        else:
            return []
    else:
        return []

    stmt = stmt.order_by(CustomerEmail.created_at.desc())
    emails = session.scalars(stmt).all()

    items: list[EmailFollowUpListItem] = []
    for email in emails:
        items.append(
            EmailFollowUpListItem(
                id=email.id,
                source_type="customer_email",
                claim_id=email.claim_id,
                claim_number=email.claim.claim_number if email.claim else None,
                claimant_name=email.claim.claimant_name if email.claim else None,
                investigation_id=email.investigation_id,
                event_type=email.event_type,
                recipient_email=email.recipient_email,
                recipient_name=email.recipient_name,
                subject=email.subject,
                message_preview=(email.body_text[:200] + "...") if len(email.body_text) > 200 else email.body_text,
                status=email.status,
                has_secure_upload=bool(email.secure_upload_url or email.secure_upload_token),
                secure_upload_url=f"/portal/upload?claim={email.claim_id}" if email.secure_upload_token else None,
                follow_up_deadline=email.follow_up_deadline,
                attempt_count=email.attempt_count or 0,
                last_error_type=email.last_error_type,
                created_at=email.created_at,
                delivered_at=email.sent_at,
            )
        )

    notif_stmt = select(NotificationDelivery)
    if employee.role == EmployeeRole.ADMIN:
        pass
    else:
        notif_stmt = notif_stmt.where(NotificationDelivery.recipient_employee_id == employee.id)

    notif_stmt = notif_stmt.order_by(NotificationDelivery.created_at.desc())
    deliveries = session.scalars(notif_stmt).all()

    claims = {c.id: c for c in session.scalars(select(Claim)).all()}

    for deliv in deliveries:
        claim_obj = None
        if deliv.application_path and "/claims/" in deliv.application_path:
            raw_id = deliv.application_path.split("/claims/")[-1].split("/")[0]
            try:
                parsed_uuid = UUID(raw_id)
                claim_obj = claims.get(parsed_uuid)
            except ValueError:
                pass

        if employee.role == EmployeeRole.CLAIMS_ADJUSTER and claim_obj and claim_obj.assigned_employee_id != employee.id:
            continue

        items.append(
            EmailFollowUpListItem(
                id=deliv.id,
                source_type="system_notification",
                claim_id=claim_obj.id if claim_obj else None,
                claim_number=claim_obj.claim_number if claim_obj else None,
                claimant_name=claim_obj.claimant_name if claim_obj else None,
                investigation_id=UUID(deliv.resource_id) if deliv.resource_id and len(deliv.resource_id) == 36 else None,
                event_type=deliv.event_type,
                recipient_email=employee.email,
                recipient_name=employee.display_name,
                subject=f"System Notification: {deliv.event_type.replace('_', ' ').title()}",
                message_preview=f"Notification recorded for {deliv.application_path}",
                status=deliv.status,
                has_secure_upload=False,
                secure_upload_url=None,
                follow_up_deadline=None,
                attempt_count=deliv.attempt_count or 0,
                last_error_type=deliv.last_error_type,
                created_at=deliv.created_at,
                delivered_at=deliv.delivered_at,
            )
        )

    items.sort(key=lambda x: x.created_at, reverse=True)
    return items


@router.get(
    "/{claim_id}/emails",
    response_model=list[CustomerEmailResponse],
)
def list_claim_emails(
    claim_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[CustomerEmailResponse]:
    """List customer emails for an authorized claim."""
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    emails = session.scalars(
        select(CustomerEmail)
        .where(CustomerEmail.claim_id == claim_id)
        .order_by(CustomerEmail.created_at.desc())
    ).all()

    return [CustomerEmailResponse.model_validate(e) for e in emails]


@router.post(
    "/{claim_id}/emails",
    response_model=CustomerEmailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_email_draft(
    claim_id: UUID,
    request: CustomerEmailDraftRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> CustomerEmailResponse:
    """Create a drafted customer email awaiting human approval."""
    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    try:
        draft = create_email_draft(
            session,
            claim=claim,
            event_type=request.event_type,
            recipient_email=str(request.recipient_email),
            recipient_name=request.recipient_name,
            requested_documents=request.requested_documents,
            follow_up_days=request.follow_up_days,
            subject=request.subject,
            body_text=request.body_text,
            body_html=request.body_html,
            created_by_employee=employee,
        )
        session.commit()
        session.refresh(draft)
        return CustomerEmailResponse.model_validate(draft)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    except Exception as exc:
        session.rollback()
        logger.error("Failed to draft customer email: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create customer email draft.",
        ) from None


@router.get(
    "/{claim_id}/emails/{email_id}",
    response_model=CustomerEmailResponse,
)
def get_customer_email(
    claim_id: UUID,
    email_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> CustomerEmailResponse:
    """Get single customer email details."""
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    email_record = session.scalar(
        select(CustomerEmail).where(
            CustomerEmail.id == email_id,
            CustomerEmail.claim_id == claim_id,
        )
    )
    if email_record is None:
        raise _not_found()

    return CustomerEmailResponse.model_validate(email_record)


@router.patch(
    "/{claim_id}/emails/{email_id}",
    response_model=CustomerEmailResponse,
)
def modify_customer_email(
    claim_id: UUID,
    email_id: UUID,
    request: CustomerEmailUpdateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> CustomerEmailResponse:
    """Modify subject or body of a drafted email before approval."""
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    email_record = session.scalar(
        select(CustomerEmail).where(
            CustomerEmail.id == email_id,
            CustomerEmail.claim_id == claim_id,
        )
    )
    if email_record is None:
        raise _not_found()

    try:
        updated = update_email_draft(
            session,
            email_id=email_id,
            employee=employee,
            subject=request.subject,
            body_text=request.body_text,
            body_html=request.body_html,
        )
        session.commit()
        session.refresh(updated)
        return CustomerEmailResponse.model_validate(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None


@router.post(
    "/{claim_id}/emails/{email_id}/approve",
    response_model=CustomerEmailResponse,
)
def approve_customer_email(
    claim_id: UUID,
    email_id: UUID,
    _request: CustomerEmailApprovalRequest | None = None,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> CustomerEmailResponse:
    """Explicit human approval gate required before an email can be sent."""
    if employee.role != EmployeeRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators are authorized to approve customer communications.",
        )
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    email_record = session.scalar(
        select(CustomerEmail).where(
            CustomerEmail.id == email_id,
            CustomerEmail.claim_id == claim_id,
        )
    )
    if email_record is None:
        raise _not_found()

    try:
        approved = approve_email(
            session,
            email_id=email_id,
            employee=employee,
        )
        session.commit()
        session.refresh(approved)
        return CustomerEmailResponse.model_validate(approved)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None


@router.post(
    "/{claim_id}/emails/{email_id}/send",
    response_model=CustomerEmailResponse,
)
def send_customer_email(
    claim_id: UUID,
    email_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> CustomerEmailResponse:
    """Dispatch an email that has passed human approval. Rejects unapproved emails."""
    if employee.role != EmployeeRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators are authorized to dispatch customer communications.",
        )
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    email_record = session.scalar(
        select(CustomerEmail).where(
            CustomerEmail.id == email_id,
            CustomerEmail.claim_id == claim_id,
        )
    )
    if email_record is None:
        raise _not_found()

    try:
        sent = dispatch_approved_email(
            session,
            email_id=email_id,
        )
        session.commit()
        session.refresh(sent)
        return CustomerEmailResponse.model_validate(sent)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    except Exception as exc:
        session.rollback()
        logger.error("Failed to send customer email %s: %s", email_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Customer email dispatch failed.",
        ) from None


@router.post(
    "/{claim_id}/emails/reminders/check",
    response_model=list[CustomerEmailResponse],
)
def check_claim_reminders(
    claim_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[CustomerEmailResponse]:
    """Check overdue document requests and generate reminder drafts awaiting approval."""
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise _not_found() from None

    reminder_drafts = check_overdue_reminders(session, claim_id=claim_id)
    session.commit()
    return [CustomerEmailResponse.model_validate(r) for r in reminder_drafts]
