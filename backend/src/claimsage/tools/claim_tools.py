"""Permission-checked claim retrieval tool."""

from uuid import UUID

from sqlalchemy.orm import Session

from claimsage.services.claim_access import (
    ClaimAccessDeniedError,
    get_authorized_claim,
)


def retrieve_authorized_claim(
    session: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
) -> dict[str, object]:
    """Retrieve selected facts only after backend authorization."""

    try:
        claim = get_authorized_claim(
            session,
            employee_id=employee_id,
            claim_id=claim_id,
        )
    except ClaimAccessDeniedError:
        raise ClaimAccessDeniedError(
            "Claim not found or access denied."
        ) from None

    return {
        "claim_id": str(claim.id),
        "claim_number": claim.claim_number,
        "claim_type": claim.claim_type,
        "status": claim.status,
        "summary": claim.summary,
        "created_at": (
            claim.created_at.isoformat()
            if claim.created_at is not None
            else None
        ),
    }
