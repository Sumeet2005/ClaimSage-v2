
"""Authorized claim-listing and claim-detail endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import Employee
from claimsage.db.session import get_db
from claimsage.schemas.claims import ClaimResponse
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
