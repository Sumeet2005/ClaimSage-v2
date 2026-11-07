"""Service for Human Review decisions, finding revisions, and workflow actions."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import (
    AuditEvent,
    Claim,
    CustomerEmail,
    Employee,
    EmployeeRole,
    InvestigationFinding,
    InvestigationFindingEdit,
    InvestigationReview,
    InvestigationRun,
)
from claimsage.schemas.human_review import FindingEditRequest, InvestigationReviewRequest
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)
from claimsage.services.customer_emails import create_email_draft

logger = logging.getLogger(__name__)

ALLOWED_REVIEWER_ROLES = {
    EmployeeRole.ADMIN,
}


class HumanReviewError(Exception):
    """Business rule or state validation error in human review workflows."""


def record_human_review(
    session: Session,
    *,
    investigation: InvestigationRun,
    employee: Employee,
    request: InvestigationReviewRequest,
) -> tuple[InvestigationReview, CustomerEmail | None]:
    """Record an authoritative human review decision with full audit logging and state transitions."""
    # 1. Authorize reviewer role
    if employee.role not in ALLOWED_REVIEWER_ROLES:
        raise HumanReviewError(
            f"Employee with role '{employee.role}' is not authorized to submit human reviews."
        )

    # 2. Check claim-level access
    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=investigation.claim_id,
        )
    except ClaimAccessDeniedError:
        raise HumanReviewError("Claim not found or access denied for reviewer.") from None

    # 3. Validate investigation state
    if investigation.status == "running":
        raise HumanReviewError("An investigation must finish before human review.")

    if (
        investigation.human_review_status == "approved"
        and request.decision == "approved"
    ):
        raise HumanReviewError("Investigation is already approved.")

    # 4. Process review decision and trigger state transitions
    email_draft: CustomerEmail | None = None
    action_type = f"investigation_review_{request.decision}"

    if request.decision == "approved":
        investigation.human_review_status = "approved"
        action_type = "investigation_human_approved"

    elif request.decision == "needs_additional_documents":
        investigation.human_review_status = "needs_additional_documents"
        action_type = "investigation_additional_documents_requested"

        # Generate a customer email draft with secure upload link (strictly DRAFTED)
        requested_docs = request.requested_documents or []
        email_draft = create_email_draft(
            session,
            claim=claim,
            investigation_id=investigation.id,
            event_type="additional_evidence_required",
            recipient_email=claim.claim_number.lower() + "@policyholder.example.com",
            recipient_name=claim.claimant_name or "Policyholder",
            requested_documents=requested_docs,
            custom_notes=request.notes,
            created_by_employee=employee,
        )

    elif request.decision == "returned_for_investigation":
        investigation.human_review_status = "returned_for_investigation"
        # Re-queue the investigation so the PostgreSQL worker picks it up
        investigation.status = "running"
        investigation.current_stage = "queued"
        investigation.worker_id = None
        investigation.lease_expires_at = None
        investigation.completed_at = None
        action_type = "investigation_returned_for_analysis"

    elif request.decision == "escalated":
        investigation.human_review_status = "escalated"
        action_type = "investigation_escalated"

    else:
        # "reviewed" or "needs_follow_up"
        investigation.human_review_status = request.decision
        action_type = "investigation_human_review_recorded"

    review = InvestigationReview(
        investigation_id=investigation.id,
        reviewer_employee_id=employee.id,
        decision=request.decision,
        notes=request.notes,
    )
    session.add(review)

    # 5. Audit event
    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=investigation.claim_id,
            investigation_id=investigation.id,
            event_category="human_review",
            action=action_type,
            outcome="success",
            resource_type="investigation",
            resource_id=str(investigation.id),
            details=(
                f"Human review decision '{request.decision}' recorded by {employee.display_name}. "
                f"Notes: {request.notes or 'None'}"
            ),
            event_metadata={
                "decision": request.decision,
                "requested_documents": request.requested_documents,
            },
        )
    )

    session.flush()
    return review, email_draft


def create_finding_edit(
    session: Session,
    *,
    finding_id: UUID,
    employee: Employee,
    request: FindingEditRequest,
) -> InvestigationFindingEdit:
    """Record a versioned human modification to an AI finding while keeping the original finding immutable."""
    finding = session.scalar(
        select(InvestigationFinding).where(InvestigationFinding.id == finding_id)
    )
    if finding is None:
        raise HumanReviewError(f"Investigation finding {finding_id} not found.")

    investigation = session.scalar(
        select(InvestigationRun).where(InvestigationRun.id == finding.investigation_id)
    )
    if investigation is None:
        raise HumanReviewError("Investigation associated with finding not found.")

    # Check authorization on the claim
    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=investigation.claim_id,
        )
    except ClaimAccessDeniedError:
        raise HumanReviewError("Claim access denied for finding modification.") from None

    # Preserving the original AI findings untouched in finding.finding_data
    edit = InvestigationFindingEdit(
        finding_id=finding.id,
        investigation_id=investigation.id,
        editor_employee_id=employee.id,
        original_data=finding.finding_data,
        edited_data=request.edited_data,
        reason=request.reason,
    )
    session.add(edit)

    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=investigation.claim_id,
            investigation_id=investigation.id,
            event_category="finding",
            action="investigation_finding_edited",
            outcome="success",
            resource_type="investigation_finding",
            resource_id=str(finding.id),
            details=f"Finding edited by {employee.display_name}. Reason: {request.reason}",
            event_metadata={
                "finding_id": str(finding.id),
                "finding_type": finding.finding_type,
                "reason": request.reason,
            },
        )
    )

    session.flush()
    return edit


def list_finding_edits(
    session: Session,
    *,
    finding_id: UUID,
    employee: Employee,
) -> list[InvestigationFindingEdit]:
    """Retrieve all human revision history for a specific finding."""
    finding = session.scalar(
        select(InvestigationFinding).where(InvestigationFinding.id == finding_id)
    )
    if finding is None:
        raise HumanReviewError(f"Investigation finding {finding_id} not found.")

    investigation = session.scalar(
        select(InvestigationRun).where(InvestigationRun.id == finding.investigation_id)
    )
    if investigation is None:
        raise HumanReviewError("Investigation associated with finding not found.")

    try:
        get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=investigation.claim_id,
        )
    except ClaimAccessDeniedError:
        raise HumanReviewError("Claim access denied.") from None

    edits = session.scalars(
        select(InvestigationFindingEdit)
        .where(InvestigationFindingEdit.finding_id == finding_id)
        .order_by(InvestigationFindingEdit.created_at.desc())
    ).all()

    return list(edits)
