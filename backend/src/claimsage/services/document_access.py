"""Authorization rules for accessing policy documents."""

from uuid import UUID

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from claimsage.db.models import (
    Employee,
    EmployeeRole,
    PolicyDocument,
    PolicyDocumentAccess,
)
from claimsage.services.claim_access import get_authorized_claim


class PolicyDocumentAccessDeniedError(Exception):
    """Raised when an employee cannot access policy documents."""


def build_policy_document_access_filter(
    session: Session,
    *,
    employee_id: UUID,
    claim_id: UUID,
) -> ColumnElement[bool]:
    """Build a SQL filter restricting policy documents to accessible records.

    Claim authorization is checked before document authorization.

    Admins and policy specialists can access all policy documents.
    Team leads and adjusters require an explicit team-level or
    claim-level document grant.

    The returned SQL expression is applied directly to the document
    retrieval query so unauthorized document text is never loaded.
    """
    employee = session.scalar(
        select(Employee).where(Employee.id == employee_id)
    )

    if employee is None:
        raise PolicyDocumentAccessDeniedError(
            "Policy document access denied."
        )

    # Defense in depth: document access never replaces claim authorization.
    get_authorized_claim(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
    )

    # Administrators and Policy Specialists have global document access.
    if employee.role in {
        EmployeeRole.ADMIN,
        EmployeeRole.POLICY_SPECIALIST,
    }:
        return true()

    # Only Adjusters and Team Leads can use scoped document grants.
    if employee.role not in {
        EmployeeRole.CLAIMS_ADJUSTER,
        EmployeeRole.TEAM_LEAD,
    }:
        raise PolicyDocumentAccessDeniedError(
            "Policy document access denied."
        )

    # A document can be accessible through an exact claim grant
    # or through a grant matching the employee's own team.
    grant_conditions = [
        PolicyDocumentAccess.claim_id == claim_id,
    ]

    if employee.team_id is not None:
        grant_conditions.append(
            PolicyDocumentAccess.team_id == employee.team_id
        )

    matching_grant = (
        select(PolicyDocumentAccess.id)
        .where(
            PolicyDocumentAccess.document_id == PolicyDocument.id,
            or_(*grant_conditions),
        )
        .exists()
    )

    return matching_grant
