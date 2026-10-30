"""Authenticated ClaimSage investigation endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from claimsage.agents.graph import run_investigation
from claimsage.api.dependencies import get_current_employee
from claimsage.db.models import Employee
from claimsage.db.session import get_db
from claimsage.schemas.agent import (
    InvestigationRequest,
    InvestigationResponse,
)

router = APIRouter(prefix="/agent", tags=["AI Agent"])


@router.post(
    "/investigations",
    response_model=InvestigationResponse,
)
def investigate_claim(
    request: InvestigationRequest,
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> InvestigationResponse:
    """Investigate a claim using the authenticated employee's identity."""

    outcome = run_investigation(
        session=session,
        employee_id=employee.id,
        claim_id=request.claim_id,
        task=request.task,
    )

    if outcome["error"] == "Claim not found or access denied.":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found or access denied.",
        )

    if outcome["error"] is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=outcome["error"],
        )

    return InvestigationResponse(
        claim_facts=outcome["claim_facts"],
        result=outcome["result"],
        error=None,
    )
