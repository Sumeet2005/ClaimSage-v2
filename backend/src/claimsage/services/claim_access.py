
"""Authorization rules for accessing ClaimSage claims."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from claimsage.db.models import Claim, Employee, EmployeeRole


class ClaimAccessDeniedError(Exception):
    """Raised when an employee is not authorized to access a claim."""


def get_authorized_claim(
    session: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
) -> Claim:
    """Return a claim only when the employee is authorized to access it.

    Admins can access all claims.
    Adjusters can access claims assigned to them.
    Team leads and policy specialists can access claims in their team.

    Missing employees and inaccessible claims use the same exception.
    """
    employee = session.scalar(
        select(Employee).where(Employee.id == employee_id)
    )

    if employee is None:
        raise ClaimAccessDeniedError("Claim not found or access denied.")

    statement = select(Claim).where(Claim.id == claim_id)

    if employee.role == EmployeeRole.ADMIN:
        claim = session.scalar(statement)

    elif employee.role == EmployeeRole.CLAIMS_ADJUSTER:
        claim = session.scalar(
            statement.where(Claim.assigned_employee_id == employee.id)
        )

    elif employee.role in {
        EmployeeRole.TEAM_LEAD,
        EmployeeRole.POLICY_SPECIALIST,
    }:
        if employee.team_id is None:
            raise ClaimAccessDeniedError(
                "Claim not found or access denied."
            )

        claim = session.scalar(
            statement.where(Claim.team_id == employee.team_id)
        )

    else:
        raise ClaimAccessDeniedError("Claim not found or access denied.")

    if claim is None:
        raise ClaimAccessDeniedError("Claim not found or access denied.")

    return claim


def list_authorized_claims(
    session: Session,
    *,
    employee_id: UUID,
) -> list[Claim]:
    """List claims using database filters for the employee's current role."""
    employee = session.scalar(
        select(Employee).where(Employee.id == employee_id)
    )

    if employee is None:
        raise ClaimAccessDeniedError("Claim not found or access denied.")

    statement = select(Claim)

    if employee.role == EmployeeRole.ADMIN:
        pass

    elif employee.role == EmployeeRole.CLAIMS_ADJUSTER:
        statement = statement.where(
            Claim.assigned_employee_id == employee.id
        )

    elif employee.role in {
        EmployeeRole.TEAM_LEAD,
        EmployeeRole.POLICY_SPECIALIST,
    }:
        if employee.team_id is None:
            return []

        statement = statement.where(Claim.team_id == employee.team_id)

    else:
        raise ClaimAccessDeniedError("Claim not found or access denied.")

    statement = statement.order_by(
        Claim.created_at.desc(),
        Claim.claim_number.asc(),
    )

    return list(session.scalars(statement).all())
