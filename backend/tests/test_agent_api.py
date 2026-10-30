"""HTTP security tests for ClaimSage investigations."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_claim_access import login


def test_investigation_requires_authentication(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Investigation requests must reject missing credentials."""
    response = client.post(
        "/api/v1/agent/investigations",
        json={
            "claim_id": str(claims_scenario["adjuster_claim_id"]),
            "task": "Summarize the claim facts.",
        },
    )

    assert response.status_code == 401


def test_investigation_rejects_invalid_token(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """Investigation requests must reject invalid bearer tokens."""
    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": "Bearer invalid-token"},
        json={
            "claim_id": str(claims_scenario["adjuster_claim_id"]),
            "task": "Summarize the claim facts.",
        },
    )

    assert response.status_code == 401


def test_adjuster_can_investigate_assigned_claim(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """An adjuster can investigate their assigned claim."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_id": str(claims_scenario["adjuster_claim_id"]),
            "task": "Summarize the recorded claim facts.",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert body["error"] is None
    assert body["claim_facts"]["claim_id"] == str(
        claims_scenario["adjuster_claim_id"]
    )

    assert body["result"] is not None
    assert body["result"]["human_review_required"] is True
    assert body["result"]["policy_review"] in {
        "evidence_retrieved",
        "no_relevant_evidence_found",
    }
    assert isinstance(body["result"]["policy_evidence"], list)
    assert body["result"]["claim"] == body["claim_facts"]


def test_adjuster_cannot_investigate_another_employees_claim(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """An adjuster cannot investigate a claim assigned to another adjuster."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_id": str(claims_scenario["other_claim_id"]),
            "task": "Summarize this claim.",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Claim not found or access denied."


def test_inaccessible_and_nonexistent_claims_use_same_response(
    client: TestClient,
    claims_scenario: dict,
) -> None:
    """The API must not disclose whether an inaccessible claim exists."""
    token = login(client, claims_scenario["adjuster_email"])
    headers = {"Authorization": f"Bearer {token}"}

    inaccessible_response = client.post(
        "/api/v1/agent/investigations",
        headers=headers,
        json={
            "claim_id": str(claims_scenario["other_claim_id"]),
            "task": "Summarize this claim.",
        },
    )

    nonexistent_response = client.post(
        "/api/v1/agent/investigations",
        headers=headers,
        json={
            "claim_id": str(uuid4()),
            "task": "Summarize this claim.",
        },
    )

    assert inaccessible_response.status_code == 404
    assert nonexistent_response.status_code == 404
    assert inaccessible_response.json() == nonexistent_response.json()


@pytest.mark.parametrize(
    "request_body",
    [
        {},
        {"claim_id": "not-a-uuid", "task": "Investigate this claim."},
        {"claim_id": str(uuid4()), "task": "   "},
    ],
)
def test_investigation_rejects_invalid_request_body(
    client: TestClient,
    claims_scenario: dict,
    request_body: dict,
) -> None:
    """Malformed or incomplete investigation requests must be rejected."""
    token = login(client, claims_scenario["adjuster_email"])

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json=request_body,
    )

    assert response.status_code == 422
