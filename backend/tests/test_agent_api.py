"""HTTP security tests for ClaimSage investigations."""

from types import SimpleNamespace

from unittest.mock import MagicMock

from uuid import UUID, uuid4

import pytest

from fastapi.testclient import TestClient

from test_claim_access import login

from claimsage.agents import graph as graph_module

from claimsage.agents.schemas import ReviewReportOutput, SupervisorPlan

from claimsage.api.routes import agent as agent_route
from claimsage.workers.investigation_worker import InvestigationWorker


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An adjuster can investigate their assigned claim."""

    token = login(client, claims_scenario["adjuster_email"])

    monkeypatch.setattr(
        graph_module,
        "create_supervisor_plan",
        MagicMock(
            return_value=SupervisorPlan(
                selected_analysts=["policy_analyst"],
                routing_rationale="Synthetic API regression test.",
                human_review_required=True,
            )
        ),
    )

    monkeypatch.setattr(
        graph_module,
        "search_claim_evidence",
        MagicMock(return_value=[]),
    )

    monkeypatch.setattr(
        graph_module,
        "analyze_review_report",
        MagicMock(
            return_value=ReviewReportOutput(
                overall_status="insufficient_evidence",
                specialist_coverage=[],
                evidence_retrieval_status="not_performed",
                evidence_scope_note="Synthetic report for API tests.",
                human_review_required=True,
            )
        ),
    )

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_id": str(claims_scenario["adjuster_claim_id"]),
            "task": "Summarize the recorded claim facts.",
        },
    )

    assert response.status_code == 202

    body = response.json()

    assert body["execution_status"] == "running"

    investigation_id = body["investigation_id"]

    inv_id = UUID(response.json()['investigation_id'])
    InvestigationWorker().execute_job(inv_id)

    result_res = client.get(
        f"/api/v1/agent/investigations/{investigation_id}/result",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert result_res.status_code == 200

    res_body = result_res.json()

    assert res_body["execution_status"] == "completed"

    assert res_body["error"] is None

    assert res_body["claim_facts"]["claim_id"] == str(claims_scenario["adjuster_claim_id"])

    assert res_body["result"] is not None

    assert res_body["result"]["human_review_required"] is True

    assert res_body["result"]["policy_review"] in {
        "evidence_retrieved",
        "no_relevant_evidence_found",
        "insufficient_evidence",
    }

    assert isinstance(res_body["result"]["policy_evidence"], list)

    assert res_body["result"]["claim"] == res_body["claim_facts"]


def test_review_report_is_serialized_in_existing_investigation_response(
    client: TestClient,
    claims_scenario: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The report is exposed through the compatible result payload."""

    token = login(client, claims_scenario["adjuster_email"])

    claim_id = str(claims_scenario["adjuster_claim_id"])

    report = {
        "overall_status": "completed",
        "observed_facts": [],
        "analyst_interpretations": [],
        "hypotheses": [],
        "conflicting_findings": [],
        "missing_information": [],
        "specialist_coverage": [
            {
                "specialist": "policy_analyst",
                "status": "unavailable",
                "analysis_included": False,
                "limitations": ["The policy analysis was unavailable."],
            }
        ],
        "evidence_retrieval_status": "limited",
        "evidence_retrieval_limitations": ["Claim retrieval was limited."],
        "evidence_scope_note": "Only retrieved evidence is represented.",
        "human_review_required": True,
    }

    monkeypatch.setattr(
        "claimsage.workers.investigation_worker.run_investigation",
        lambda **_kwargs: {
            "claim_facts": {"claim_id": claim_id},
            "result": {
                "review_report": report,
                "review_report_status": "completed",
                "human_review_required": True,
                "limitations": [],
            },
            "error": None,
        },
    )

    monkeypatch.setattr(
        "claimsage.workers.investigation_worker.dispatch_notification",
        lambda *_args, **_kwargs: None,
    )

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_id": claim_id,
            "task": "Review the investigation.",
        },
    )

    assert response.status_code == 202

    body = response.json()

    assert body["execution_status"] == "running"

    investigation_id = body["investigation_id"]

    inv_id = UUID(response.json()['investigation_id'])
    InvestigationWorker().execute_job(inv_id)

    result_res = client.get(
        f"/api/v1/agent/investigations/{investigation_id}/result",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert result_res.status_code == 200

    res_body = result_res.json()

    assert res_body["execution_status"] == "incomplete"

    assert res_body["error"] is None

    assert res_body["claim_facts"] == {"claim_id": claim_id}

    assert res_body["result"]["review_report"] == report

    assert res_body["result"]["review_report_status"] == "completed"

    assert res_body["result"]["human_review_required"] is True

    assert "employee_id" not in res_body["result"]

    assert "api_key" not in res_body["result"]

    detail = client.get(
        f"/api/v1/agent/investigations/{investigation_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert detail.status_code == 200

    assert detail.json()["status"] == "incomplete"

    notifications = client.get(
        f"/api/v1/agent/investigations/{investigation_id}/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert notifications.status_code == 200

    assert {row["event_type"] for row in notifications.json()} == {
        "investigation_completed",
        "human_review_required",
    }

    assert all(row["status"] == "pending" for row in notifications.json())

    other_token = login(client, claims_scenario["other_adjuster_email"])

    denied_notifications = client.get(
        f"/api/v1/agent/investigations/{investigation_id}/notifications",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert denied_notifications.status_code == 404


def test_failed_report_limitation_is_returned_with_investigation(
    client: TestClient,
    claims_scenario: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report unavailability must not discard the investigation response."""

    token = login(client, claims_scenario["adjuster_email"])

    claim_id = str(claims_scenario["adjuster_claim_id"])

    limitation = (
        "Review & Report generation is temporarily unavailable. "
        "Specialist results were retained for mandatory human review."
    )

    monkeypatch.setattr(
        "claimsage.workers.investigation_worker.run_investigation",
        lambda **_kwargs: {
            "claim_facts": {"claim_id": claim_id},
            "result": {
                "review_report": None,
                "review_report_status": "unavailable",
                "human_review_required": True,
                "limitations": [limitation],
                "intake_analysis": {"summary": "Retained specialist output."},
            },
            "error": None,
        },
    )

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_id": claim_id,
            "task": "Review the investigation.",
        },
    )

    assert response.status_code == 202

    body = response.json()

    assert body["execution_status"] == "running"

    investigation_id = body["investigation_id"]

    inv_id = UUID(response.json()['investigation_id'])
    InvestigationWorker().execute_job(inv_id)

    result_res = client.get(
        f"/api/v1/agent/investigations/{investigation_id}/result",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert result_res.status_code == 200

    res_body = result_res.json()

    assert res_body["execution_status"] == "incomplete"

    assert res_body["error"] is None

    assert res_body["result"]["review_report"] is None

    assert res_body["result"]["review_report_status"] == "unavailable"

    assert res_body["result"]["intake_analysis"] == {"summary": "Retained specialist output."}

    assert res_body["result"]["limitations"] == [limitation]

    assert res_body["result"]["human_review_required"] is True


def test_repair_estimate_reference_is_forwarded_to_graph(
    client: TestClient,
    claims_scenario: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authorized Motor estimate reference reaches the shared graph."""

    token = login(client, claims_scenario["other_adjuster_email"])

    claim_id = str(claims_scenario["other_claim_id"])

    estimate_id = uuid4()

    forwarded: dict[str, object] = {}

    def fake_run_investigation(**kwargs):

        forwarded.update(kwargs)

        return {
            "claim_facts": {"claim_id": claim_id},
            "result": {"human_review_required": True},
            "error": None,
        }

    monkeypatch.setattr(
        "claimsage.workers.investigation_worker.run_investigation",
        fake_run_investigation,
    )

    response = client.post(
        "/api/v1/agent/investigations",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "claim_id": claim_id,
            "task": "Review the synthetic repair estimate.",
            "repair_estimate_document_id": str(estimate_id),
        },
    )

    assert response.status_code == 202

    inv_id = UUID(response.json()['investigation_id'])
    InvestigationWorker().execute_job(inv_id)

    assert forwarded["repair_estimate_document_id"] == estimate_id


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


