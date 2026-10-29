"""HTTP tests for claim listing and access control."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from claimsage.db.models import (
    AuditEvent,
    Claim,
    Employee,
    EmployeeRole,
)
from claimsage.db.session import SessionLocal
from claimsage.main import app
from claimsage.services.auth import hash_password

TEST_PASSWORD = "ClaimSageTestPassword2026!"


@pytest.fixture
def claims_scenario() -> Generator[dict, None, None]:
    """Create isolated synthetic employees and claims for API tests."""
    suffix = uuid4().hex
    password_hash = hash_password(TEST_PASSWORD)

    adjuster = Employee(
        email=f"adjuster-{suffix}@claimsage.local",
        display_name="Test Adjuster",
        password_hash=password_hash,
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"property-{suffix}",
    )
    other_adjuster = Employee(
        email=f"other-adjuster-{suffix}@claimsage.local",
        display_name="Other Test Adjuster",
        password_hash=password_hash,
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id=f"auto-{suffix}",
    )
    lead = Employee(
        email=f"lead-{suffix}@claimsage.local",
        display_name="Test Team Lead",
        password_hash=password_hash,
        role=EmployeeRole.TEAM_LEAD,
        team_id=f"property-{suffix}",
    )
    admin = Employee(
        email=f"admin-{suffix}@claimsage.local",
        display_name="Test Admin",
        password_hash=password_hash,
        role=EmployeeRole.ADMIN,
        team_id=None,
    )

    with SessionLocal.begin() as session:
        session.add_all([adjuster, other_adjuster, lead, admin])
        session.flush()

        claim_assigned_to_adjuster = Claim(
            claim_number=f"CLM-T-{suffix}-1",
            claimant_name="Synthetic Claimant One",
            claim_type="property",
            status="under_review",
            assigned_employee_id=adjuster.id,
            team_id=adjuster.team_id,
            summary="Synthetic test claim assigned to the adjuster.",
        )
        claim_assigned_to_other = Claim(
            claim_number=f"CLM-T-{suffix}-2",
            claimant_name="Synthetic Claimant Two",
            claim_type="auto",
            status="under_review",
            assigned_employee_id=other_adjuster.id,
            team_id=other_adjuster.team_id,
            summary="Synthetic test claim assigned to another adjuster.",
        )
        unassigned_team_claim = Claim(
            claim_number=f"CLM-T-{suffix}-3",
            claimant_name="Synthetic Claimant Three",
            claim_type="property",
            status="documents_pending",
            assigned_employee_id=None,
            team_id=adjuster.team_id,
            summary="Synthetic test claim for team-level access.",
        )

        session.add_all(
            [
                claim_assigned_to_adjuster,
                claim_assigned_to_other,
                unassigned_team_claim,
            ]
        )
        session.flush()

        employee_ids = [
            adjuster.id,
            other_adjuster.id,
            lead.id,
            admin.id,
        ]
        claim_ids = [
            claim_assigned_to_adjuster.id,
            claim_assigned_to_other.id,
            unassigned_team_claim.id,
        ]

        scenario = {
            "adjuster_email": adjuster.email,
            "other_adjuster_email": other_adjuster.email,
            "lead_email": lead.email,
            "admin_email": admin.email,
            "adjuster_claim_id": claim_assigned_to_adjuster.id,
            "other_claim_id": claim_assigned_to_other.id,
            "team_claim_id": unassigned_team_claim.id,
            "claim_numbers": {
                claim_assigned_to_adjuster.claim_number,
                claim_assigned_to_other.claim_number,
                unassigned_team_claim.claim_number,
            },
            "team_claim_numbers": {
                claim_assigned_to_adjuster.claim_number,
                unassigned_team_claim.claim_number,
            },
        }

    try:
        yield scenario
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(Claim).where(Claim.id.in_(claim_ids))
            )
            session.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_employee_id.in_(employee_ids)
                )
            )
            session.execute(
                delete(Employee).where(Employee.id.in_(employee_ids))
            )


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the API."""
    return TestClient(app)


def login(client: TestClient, email: str) -> str:
    """Log in a synthetic employee and return their access token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_adjuster_lists_only_assigned_claims(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Adjusters must not see claims assigned to other employees."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.get(
        "/api/v1/claims",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    claims = response.json()
    assert len(claims) == 1
    assert claims[0]["id"] == str(claims_scenario["adjuster_claim_id"])


def test_team_lead_lists_claims_in_their_team(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Team leads may see assigned and unassigned claims in their team."""
    token = login(client, claims_scenario["lead_email"])

    response = client.get(
        "/api/v1/claims",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    returned_numbers = {
        claim["claim_number"] for claim in response.json()
    }

    assert returned_numbers == claims_scenario["team_claim_numbers"]


def test_admin_can_list_all_claims(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Admins may see every claim, including pre-existing demo claims."""
    token = login(client, claims_scenario["admin_email"])

    response = client.get(
        "/api/v1/claims",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    returned_numbers = {
        claim["claim_number"] for claim in response.json()
    }

    # Every claim created by this test scenario must be visible.
    assert claims_scenario["claim_numbers"].issubset(returned_numbers)

    # Confirm the API also returns existing seeded demo claims.
    assert {
        "CLM-DEMO-1001",
        "CLM-DEMO-1002",
        "CLM-DEMO-2001",
    }.issubset(returned_numbers)


def test_adjuster_can_get_assigned_claim(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """An adjuster can retrieve a claim assigned to them."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.get(
        f"/api/v1/claims/{claims_scenario['adjuster_claim_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(
        claims_scenario["adjuster_claim_id"]
    )


def test_adjuster_cannot_get_another_employees_claim(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """An adjuster must not retrieve a claim assigned to another employee."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.get(
        f"/api/v1/claims/{claims_scenario['other_claim_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Claim not found or access denied."


def test_nonexistent_claim_returns_same_not_found_response(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """A nonexistent claim uses the same response as an inaccessible claim."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.get(
        f"/api/v1/claims/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Claim not found or access denied."


def test_claim_list_requires_authentication(client: TestClient) -> None:
    """The claim list must not be publicly accessible."""
    response = client.get("/api/v1/claims")

    assert response.status_code == 401


def test_claim_detail_rejects_invalid_uuid(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Malformed claim IDs should fail request validation."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.get(
        "/api/v1/claims/not-a-uuid",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422