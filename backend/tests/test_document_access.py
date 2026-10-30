
"""Database-backed tests for policy document authorization."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from claimsage.db.models import (
    Claim,
    Employee,
    EmployeeRole,
    PolicyDocument,
    PolicyDocumentAccess,
)
from claimsage.db.session import SessionLocal
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.services.document_access import (
    build_policy_document_access_filter,
)


@pytest.fixture
def document_access_scenario() -> Generator[dict, None, None]:
    """Create isolated PostgreSQL records for document access tests."""

    suffix = uuid4().hex
    team_id = f"test-team-{suffix}"
    other_team_id = f"other-team-{suffix}"

    with SessionLocal.begin() as session:
        adjuster = Employee(
            email=f"adjuster-{suffix}@claimsage.local",
            display_name="Synthetic Adjuster",
            role=EmployeeRole.CLAIMS_ADJUSTER,
            team_id=team_id,
        )
        other_adjuster = Employee(
            email=f"other-adjuster-{suffix}@claimsage.local",
            display_name="Synthetic Other Adjuster",
            role=EmployeeRole.CLAIMS_ADJUSTER,
            team_id=other_team_id,
        )
        lead = Employee(
            email=f"lead-{suffix}@claimsage.local",
            display_name="Synthetic Team Lead",
            role=EmployeeRole.TEAM_LEAD,
            team_id=team_id,
        )
        specialist = Employee(
            email=f"specialist-{suffix}@claimsage.local",
            display_name="Synthetic Policy Specialist",
            role=EmployeeRole.POLICY_SPECIALIST,
            team_id=team_id,
        )
        admin = Employee(
            email=f"admin-{suffix}@claimsage.local",
            display_name="Synthetic Administrator",
            role=EmployeeRole.ADMIN,
            team_id=None,
        )

        session.add_all(
            [
                adjuster,
                other_adjuster,
                lead,
                specialist,
                admin,
            ]
        )
        session.flush()

        adjuster_claim = Claim(
            claim_number=f"CLM-DOC-{suffix}-1",
            claimant_name="Synthetic Claimant One",
            claim_type="property",
            status="under_review",
            assigned_employee_id=adjuster.id,
            team_id=team_id,
            summary="Synthetic claim assigned to test adjuster.",
        )
        other_claim = Claim(
            claim_number=f"CLM-DOC-{suffix}-2",
            claimant_name="Synthetic Claimant Two",
            claim_type="auto",
            status="under_review",
            assigned_employee_id=other_adjuster.id,
            team_id=other_team_id,
            summary="Synthetic claim assigned to another adjuster.",
        )

        session.add_all([adjuster_claim, other_claim])
        session.flush()

        def create_document(filename: str) -> PolicyDocument:
            document = PolicyDocument(
                filename=filename,
                checksum_sha256=uuid4().hex * 2,
                mime_type="application/pdf",
                file_size_bytes=100,
                uploaded_by_employee_id=admin.id,
                status="processed",
            )
            session.add(document)
            session.flush()
            return document

        team_document = create_document("team-policy.pdf")
        claim_document = create_document("claim-policy.pdf")
        other_team_document = create_document("other-team-policy.pdf")
        ungranted_document = create_document("ungranted-policy.pdf")

        session.add_all(
            [
                PolicyDocumentAccess(
                    document_id=team_document.id,
                    team_id=team_id,
                    granted_by_employee_id=admin.id,
                ),
                PolicyDocumentAccess(
                    document_id=claim_document.id,
                    claim_id=adjuster_claim.id,
                    granted_by_employee_id=admin.id,
                ),
                PolicyDocumentAccess(
                    document_id=other_team_document.id,
                    team_id=other_team_id,
                    granted_by_employee_id=admin.id,
                ),
            ]
        )
        session.flush()

        scenario = {
            "employee_ids": [
                adjuster.id,
                other_adjuster.id,
                lead.id,
                specialist.id,
                admin.id,
            ],
            "claim_ids": [
                adjuster_claim.id,
                other_claim.id,
            ],
            "document_ids": [
                team_document.id,
                claim_document.id,
                other_team_document.id,
                ungranted_document.id,
            ],
            "adjuster_id": adjuster.id,
            "other_adjuster_id": other_adjuster.id,
            "lead_id": lead.id,
            "specialist_id": specialist.id,
            "admin_id": admin.id,
            "adjuster_claim_id": adjuster_claim.id,
            "other_claim_id": other_claim.id,
            "team_document_id": team_document.id,
            "claim_document_id": claim_document.id,
            "other_team_document_id": other_team_document.id,
            "ungranted_document_id": ungranted_document.id,
        }

    try:
        yield scenario
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(PolicyDocument).where(
                    PolicyDocument.id.in_(scenario["document_ids"])
                )
            )
            session.execute(
                delete(Claim).where(
                    Claim.id.in_(scenario["claim_ids"])
                )
            )
            session.execute(
                delete(Employee).where(
                    Employee.id.in_(scenario["employee_ids"])
                )
            )


def get_accessible_document_ids(
    session,
    *,
    employee_id,
    claim_id,
) -> set:
    """Execute the real SQL document authorization filter."""

    access_filter = build_policy_document_access_filter(
        session,
        employee_id=employee_id,
        claim_id=claim_id,
    )

    return set(
        session.scalars(
            select(PolicyDocument.id).where(access_filter)
        ).all()
    )


def test_adjuster_can_access_team_and_claim_grants(
    document_access_scenario,
) -> None:
    """An adjuster can access matching team and claim grants."""
    scenario = document_access_scenario

    with SessionLocal() as session:
        accessible = get_accessible_document_ids(
            session,
            employee_id=scenario["adjuster_id"],
            claim_id=scenario["adjuster_claim_id"],
        )

    assert accessible == {
        scenario["team_document_id"],
        scenario["claim_document_id"],
    }


def test_team_lead_can_access_team_grants(
    document_access_scenario,
) -> None:
    """A team lead can access documents granted to their team."""
    scenario = document_access_scenario

    with SessionLocal() as session:
        accessible = get_accessible_document_ids(
            session,
            employee_id=scenario["lead_id"],
            claim_id=scenario["adjuster_claim_id"],
        )

    assert accessible == {
        scenario["team_document_id"],
        scenario["claim_document_id"],
    }


def test_admin_can_access_all_documents(
    document_access_scenario,
) -> None:
    """An admin can access documents regardless of explicit grants."""
    scenario = document_access_scenario

    with SessionLocal() as session:
        accessible = get_accessible_document_ids(
            session,
            employee_id=scenario["admin_id"],
            claim_id=scenario["other_claim_id"],
        )

    # The database may contain pre-existing documents.
    # Verify that every document created by this scenario is accessible.
    assert set(scenario["document_ids"]).issubset(accessible)


def test_policy_specialist_can_access_all_documents(
    document_access_scenario,
) -> None:
    """A policy specialist can access all policy documents."""
    scenario = document_access_scenario

    with SessionLocal() as session:
        accessible = get_accessible_document_ids(
            session,
            employee_id=scenario["specialist_id"],
            claim_id=scenario["adjuster_claim_id"],
        )

    # The database may contain pre-existing documents.
    # Verify that every document created by this scenario is accessible.
    assert set(scenario["document_ids"]).issubset(accessible)


def test_documents_without_matching_grants_are_excluded(
    document_access_scenario,
) -> None:
    """An adjuster cannot access unrelated or ungranted documents."""
    scenario = document_access_scenario

    with SessionLocal() as session:
        accessible = get_accessible_document_ids(
            session,
            employee_id=scenario["adjuster_id"],
            claim_id=scenario["adjuster_claim_id"],
        )

    assert scenario["other_team_document_id"] not in accessible
    assert scenario["ungranted_document_id"] not in accessible


def test_claim_grant_cannot_bypass_claim_authorization(
    document_access_scenario,
) -> None:
    """An adjuster cannot use another employee's claim-level grant."""
    scenario = document_access_scenario

    with SessionLocal() as session:
        with pytest.raises(ClaimAccessDeniedError):
            get_accessible_document_ids(
                session,
                employee_id=scenario["other_adjuster_id"],
                claim_id=scenario["adjuster_claim_id"],
            )
