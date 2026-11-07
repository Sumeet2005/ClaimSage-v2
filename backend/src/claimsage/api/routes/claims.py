"""Authorized claim-listing, claim-creation, and claim-detail endpoints."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import AuditEvent, Claim, Employee, EmployeeRole
from claimsage.db.session import get_db
from claimsage.schemas.claims import (
    ClaimCreateRequest,
    ClaimPolicyMetadataUpdate,
    ClaimResponse,
)
from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
    list_authorized_claims,
)

router = APIRouter(prefix="/claims", tags=["Claims"])


@router.get("", response_model=list[ClaimResponse])
def list_claims(
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> list[ClaimResponse]:
    """List only the claims the authenticated employee may access."""
    try:
        claims = list_authorized_claims(
            session,
            employee_id=employee.id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

    return [ClaimResponse.model_validate(claim) for claim in claims]


@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim(
    payload: ClaimCreateRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> ClaimResponse:
    """Create a new claim with authorization, duplicate prevention, and audit logging."""
    if employee.role not in {
        EmployeeRole.ADMIN,
        EmployeeRole.TEAM_LEAD,
        EmployeeRole.CLAIMS_ADJUSTER,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee does not have permission to create claims.",
        )

    # Check for existing duplicate claim number
    existing = session.scalar(
        select(Claim).where(Claim.claim_number == payload.claim_number)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Claim with number '{payload.claim_number}' already exists.",
        )

    assigned_id = payload.assigned_employee_id or employee.id
    team_id = payload.team_id or employee.team_id

    claim = Claim(
        id=uuid4(),
        claim_number=payload.claim_number,
        claimant_name=payload.claimant_name,
        claim_type=payload.claim_type,
        status="under_review",
        summary=payload.summary,
        loss_date=payload.loss_date,
        policy_identifier=payload.policy_identifier,
        insurer_name=payload.insurer_name,
        product_name=payload.product_name,
        team_id=team_id,
        assigned_employee_id=assigned_id,
        created_at=datetime.now(UTC),
    )
    session.add(claim)
    session.flush()

    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=claim.id,
            event_category="claim",
            action="claim_created",
            outcome="success",
            resource_type="claim",
            resource_id=str(claim.id),
            details=(
                f"Created {claim.claim_type} claim {claim.claim_number} "
                f"for claimant {claim.claimant_name}."
            ),
            event_metadata={
                "claim_number": claim.claim_number,
                "claim_type": claim.claim_type,
                "loss_date": (
                    claim.loss_date.isoformat() if claim.loss_date else None
                ),
            },
        )
    )

    try:
        session.commit()
        session.refresh(claim)
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Claim could not be created.",
        ) from None

    return ClaimResponse.model_validate(claim)


@router.get("/{claim_id}", response_model=ClaimResponse)
def get_claim(
    claim_id: UUID,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> ClaimResponse:
    """Return one claim only if the employee is authorized to access it."""
    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

    return ClaimResponse.model_validate(claim)


@router.patch(
    "/{claim_id}/policy-metadata",
    response_model=ClaimResponse,
)
def update_claim_policy_metadata(
    claim_id: UUID,
    payload: ClaimPolicyMetadataUpdate,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> ClaimResponse:
    """Save verified claim policy identity, source details, and loss date."""

    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee.id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        ) from None

    if claim.claim_type.strip().casefold() == "health" and (
        payload.insurer_name is None or payload.product_name is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Health claim policy metadata requires verified insurer "
                "and product names."
            ),
        )

    claim.policy_identifier = payload.policy_identifier
    claim.insurer_name = payload.insurer_name
    claim.product_name = payload.product_name
    claim.loss_date = payload.loss_date
    verified_fields = (
        "policy identity, insurer, product, and loss date"
        if payload.insurer_name is not None and payload.product_name is not None
        else "policy identifier and loss date"
    )
    session.add(
        AuditEvent(
            actor_type="employee",
            actor_id=employee.display_name,
            actor_employee_id=employee.id,
            claim_id=claim.id,
            event_category="claim",
            action="claim_policy_metadata_verified",
            outcome="success",
            resource_type="claim",
            resource_id=str(claim.id),
            details=(
                f"Claim {verified_fields} were verified against "
                "source documentation."
            ),
            event_metadata={
                "policy_identifier": claim.policy_identifier,
                "loss_date": (
                    claim.loss_date.isoformat()
                    if hasattr(claim.loss_date, "isoformat")
                    else str(claim.loss_date)
                ),
            },
        )
    )
    try:
        session.commit()
        session.refresh(claim)
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Claim policy metadata could not be saved.",
        ) from None

    return ClaimResponse.model_validate(claim)
