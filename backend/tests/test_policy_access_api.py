"""Integration tests for policy document access-management APIs."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from test_claim_access import TEST_PASSWORD, login

from claimsage.db.models import (
    AuditEvent,
    Employee,
    EmployeeRole,
    PolicyDocument,
    PolicyDocumentAccess,
)
from claimsage.db.session import SessionLocal
from claimsage.services.auth import hash_password

GRANT_URL = "/api/v1/policies/documents"
SPECIALIST_PASSWORD = TEST_PASSWORD


@pytest.fixture
def access_api_scenario(
    claims_scenario: dict,
) -> Generator[dict, None, None]:
    """Create isolated document and Policy Specialist records."""

    suffix = uuid4().hex

    with SessionLocal.begin() as session:
        admin = session.scalar(
            select(Employee).where(
                Employee.email == claims_scenario["admin_email"]
            )
        )
        assert admin is not None

        specialist = Employee(
            email=f"policy-specialist-{suffix}@claimsage.local",
            display_name="Test Policy Specialist",
            password_hash=hash_password(SPECIALIST_PASSWORD),
            role=EmployeeRole.POLICY_SPECIALIST,
            team_id=f"policy-{suffix}",
        )

        session.add(specialist)
        session.flush()

        document = PolicyDocument(
            filename=f"access-test-{suffix}.pdf",
            checksum_sha256=uuid4().hex + uuid4().hex,
            mime_type="application/pdf",
            file_size_bytes=1024,
            uploaded_by_employee_id=admin.id,
            status="processed",
        )

        session.add(document)
        session.flush()

        scenario = {
            "document_id": document.id,
            "specialist_id": specialist.id,
            "specialist_email": specialist.email,
            "admin_email": admin.email,
            "adjuster_email": claims_scenario["adjuster_email"],
            "lead_email": claims_scenario["lead_email"],
            "claim_id": claims_scenario["adjuster_claim_id"],
        }

    try:
        yield scenario
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(PolicyDocument).where(
                    PolicyDocument.id == scenario["document_id"]
                )
            )

            session.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_employee_id
                    == scenario["specialist_id"]
                )
            )

            session.execute(
                delete(Employee).where(
                    Employee.id == scenario["specialist_id"]
                )
            )


def auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Create Bearer authorization headers."""

    token = login(client, email)
    return {"Authorization": f"Bearer {token}"}


def grant_team(
    client: TestClient,
    headers: dict[str, str],
    document_id,
    team_id: str = "synthetic-property-team",
):
    """Create a team access grant through the API."""

    return client.post(
        f"{GRANT_URL}/{document_id}/access-grants",
        headers=headers,
        json={"team_id": team_id},
    )


def test_admin_can_grant_team_access(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Admins can grant access to a team."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    response = grant_team(
        client,
        headers,
        access_api_scenario["document_id"],
    )

    assert response.status_code == 201

    body = response.json()

    assert body["document_id"] == str(
        access_api_scenario["document_id"]
    )
    assert body["team_id"] == "synthetic-property-team"
    assert body["claim_id"] is None
    assert body["granted_by_employee_id"]

    with SessionLocal() as session:
        grant = session.get(PolicyDocumentAccess, body["id"])

        assert grant is not None

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id
                == str(access_api_scenario["document_id"]),
                AuditEvent.action == "policy_document_access_granted",
                AuditEvent.actor_employee_id == grant.granted_by_employee_id,
            )
        )

        assert audit is not None


def test_policy_specialist_can_grant_claim_access(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Policy Specialists can grant access to a specific claim."""

    headers = auth_headers(
        client,
        access_api_scenario["specialist_email"],
    )

    response = client.post(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants",
        headers=headers,
        json={"claim_id": str(access_api_scenario["claim_id"])},
    )

    assert response.status_code == 201

    body = response.json()

    assert body["claim_id"] == str(
        access_api_scenario["claim_id"]
    )
    assert body["team_id"] is None
    assert body["granted_by_employee_id"] == str(
        access_api_scenario["specialist_id"]
    )


def test_duplicate_grant_returns_conflict(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Duplicate grants return HTTP 409."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    first = grant_team(
        client,
        headers,
        access_api_scenario["document_id"],
    )

    second = grant_team(
        client,
        headers,
        access_api_scenario["document_id"],
    )

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.parametrize(
    "email_key",
    ["adjuster_email", "lead_email"],
)
def test_unauthorized_roles_cannot_grant_access(
    client: TestClient,
    access_api_scenario: dict,
    email_key: str,
) -> None:
    """Adjusters and Team Leads cannot manage document access."""

    headers = auth_headers(
        client,
        access_api_scenario[email_key],
    )

    response = grant_team(
        client,
        headers,
        access_api_scenario["document_id"],
    )

    assert response.status_code == 403


def test_grant_requires_authentication(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Unauthenticated requests cannot create grants."""

    response = client.post(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants",
        json={"team_id": "synthetic-property-team"},
    )

    assert response.status_code == 401


def test_grant_rejects_nonexistent_document(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Granting access to a nonexistent document returns 404."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    response = grant_team(
        client,
        headers,
        uuid4(),
    )

    assert response.status_code == 404


def test_grant_rejects_nonexistent_claim(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Claim-level grants require an existing claim."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    response = client.post(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants",
        headers=headers,
        json={"claim_id": str(uuid4())},
    )

    assert response.status_code == 404


def test_grant_rejects_invalid_scope(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Requests must provide exactly one access scope."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    response = client.post(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants",
        headers=headers,
        json={
            "team_id": "synthetic-property-team",
            "claim_id": str(access_api_scenario["claim_id"]),
        },
    )

    assert response.status_code == 422


def test_admin_can_revoke_grant_and_audit_event_is_created(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Revocation deletes the grant and creates an audit event."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    grant_response = grant_team(
        client,
        headers,
        access_api_scenario["document_id"],
    )

    assert grant_response.status_code == 201

    grant_id = grant_response.json()["id"]

    revoke_response = client.delete(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants/{grant_id}",
        headers=headers,
    )

    assert revoke_response.status_code == 204

    with SessionLocal() as session:
        grant = session.get(PolicyDocumentAccess, grant_id)
        assert grant is None

        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id
                == str(access_api_scenario["document_id"]),
                AuditEvent.action == "policy_document_access_revoked",
            )
        )

        assert audit is not None


def test_revoke_requires_authorized_role(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Adjusters cannot revoke document access grants."""

    admin_headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    grant_response = grant_team(
        client,
        admin_headers,
        access_api_scenario["document_id"],
    )

    grant_id = grant_response.json()["id"]

    adjuster_headers = auth_headers(
        client,
        access_api_scenario["adjuster_email"],
    )

    response = client.delete(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants/{grant_id}",
        headers=adjuster_headers,
    )

    assert response.status_code == 403


def test_revoke_rejects_grant_from_another_document(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """A grant cannot be revoked using a different document ID."""

    headers = auth_headers(
        client,
        access_api_scenario["admin_email"],
    )

    grant_response = grant_team(
        client,
        headers,
        access_api_scenario["document_id"],
    )

    grant_id = grant_response.json()["id"]

    response = client.delete(
        f"{GRANT_URL}/{uuid4()}/access-grants/{grant_id}",
        headers=headers,
    )

    assert response.status_code == 404

    with SessionLocal() as session:
        assert session.get(PolicyDocumentAccess, grant_id) is not None


def test_revoke_requires_authentication(
    client: TestClient,
    access_api_scenario: dict,
) -> None:
    """Unauthenticated requests cannot revoke grants."""

    response = client.delete(
        f"{GRANT_URL}/{access_api_scenario['document_id']}/access-grants/{uuid4()}"
    )

    assert response.status_code == 401
