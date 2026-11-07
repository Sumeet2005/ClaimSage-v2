"""Unit tests for Phase 2: Asynchronous investigation execution and lifecycle."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from claimsage.api.routes import agent as agent_route
from claimsage.api.routes import investigations as investigations_route
from claimsage.db.models import Claim, Employee, EmployeeRole, InvestigationRun
from claimsage.schemas.agent import InvestigationRequest, InvestigationResponse
from claimsage.services.claim_access import ClaimAccessDeniedError
from claimsage.workers.investigation_worker import InvestigationWorker


@pytest.fixture
def mock_employee() -> Employee:
    return Employee(
        id=uuid4(),
        email="adjuster@claimsage.local",
        display_name="Test Adjuster",
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="health-team",
    )


@pytest.fixture
def mock_claim(mock_employee: Employee) -> Claim:
    return Claim(
        id=uuid4(),
        claim_number="CLM-TEST-001",
        claimant_name="Test Claimant",
        claim_type="Health",
        policy_identifier="POL-12345",
        status="under_review",
        assigned_employee_id=mock_employee.id,
    )


def test_investigate_claim_returns_202_accepted(
    mock_employee: Employee,
    mock_claim: Claim,
) -> None:
    """investigate_claim creates a durable queued job and returns HTTP 202."""
    session = MagicMock()
    session.scalar.return_value = None

    run_id = uuid4()
    mock_run = MagicMock()
    mock_run.id = run_id
    mock_run.status = "running"
    mock_run.current_stage = "queued"

    with (
        patch.object(agent_route, "get_authorized_claim", return_value=mock_claim),
        patch.object(agent_route, "create_investigation_run", return_value=mock_run) as mock_create,
    ):
        request = InvestigationRequest(
            claim_id=mock_claim.id,
            task="Verify billing consistency.",
        )

        response = agent_route.investigate_claim(
            request=request,
            employee=mock_employee,
            session=session,
        )

        assert isinstance(response, InvestigationResponse)
        assert response.investigation_id == run_id
        assert response.execution_status == "running"
        assert response.status == "running"
        assert response.claim_facts is None
        assert response.result is None
        assert response.error is None

        mock_create.assert_called_once_with(
            session,
            claim=mock_claim,
            employee_id=mock_employee.id,
            task="Verify billing consistency.",
            repair_estimate_document_id=None,
        )


def test_investigate_claim_rejects_duplicate_running_investigation(
    mock_employee: Employee,
    mock_claim: Claim,
) -> None:
    """Prevent concurrent duplicate executions for the same claim with 409 Conflict."""
    session = MagicMock()
    existing_active = MagicMock()
    existing_active.id = uuid4()
    existing_active.status = "running"
    existing_active.created_at = datetime.now(UTC) - timedelta(minutes=2)
    existing_active.lease_expires_at = None
    existing_active.updated_at = datetime.now(UTC) - timedelta(minutes=2)
    session.scalar.return_value = existing_active

    with patch.object(agent_route, "get_authorized_claim", return_value=mock_claim):
        request = InvestigationRequest(
            claim_id=mock_claim.id,
            task="Duplicate task.",
        )

        with pytest.raises(HTTPException) as exc_info:
            agent_route.investigate_claim(
                request=request,
                employee=mock_employee,
                session=session,
            )

        assert exc_info.value.status_code == 409
        assert "already in progress" in exc_info.value.detail


def test_investigate_claim_recovers_from_stale_timed_out_investigation(
    mock_employee: Employee,
    mock_claim: Claim,
) -> None:
    """An investigation stuck in 'running' for > 15 minutes is failed and bypassed."""
    session = MagicMock()
    stale_run = MagicMock()
    stale_run.id = uuid4()
    stale_run.status = "running"
    stale_run.created_at = datetime.now(UTC) - timedelta(minutes=20)
    stale_run.lease_expires_at = None
    stale_run.updated_at = datetime.now(UTC) - timedelta(minutes=20)
    session.scalar.return_value = stale_run

    new_run_id = uuid4()
    new_run = MagicMock()
    new_run.id = new_run_id
    new_run.status = "running"

    with (
        patch.object(agent_route, "get_authorized_claim", return_value=mock_claim),
        patch.object(agent_route, "create_investigation_run", return_value=new_run),
    ):
        request = InvestigationRequest(
            claim_id=mock_claim.id,
            task="New task after stale run.",
        )

        response = agent_route.investigate_claim(
            request=request,
            employee=mock_employee,
            session=session,
        )

        assert stale_run.status == "failed"
        assert stale_run.failure_type == "InvestigationTimeout"
        session.commit.assert_called()
        assert response.investigation_id == new_run_id


def test_investigate_claim_denies_unauthorized_access(
    mock_employee: Employee,
) -> None:
    """Unauthorized claim access returns 404 without enqueuing work."""
    session = MagicMock()

    with patch.object(
        agent_route,
        "get_authorized_claim",
        side_effect=ClaimAccessDeniedError,
    ):
        request = InvestigationRequest(
            claim_id=uuid4(),
            task="Unauthorized task.",
        )

        with pytest.raises(HTTPException) as exc_info:
            agent_route.investigate_claim(
                request=request,
                employee=mock_employee,
                session=session,
            )

        assert exc_info.value.status_code == 404


def test_run_investigation_background_executes_isolated_session(
    mock_claim: Claim,
) -> None:
    """Worker uses an isolated SessionLocal, runs the graph, and persists outcome."""
    inv_id = uuid4()
    mock_run = MagicMock()
    mock_run.id = inv_id

    worker_session = MagicMock()
    worker_session.__enter__.return_value = worker_session
    worker_session.get.side_effect = lambda model, obj_id: (
        mock_run if model is InvestigationRun else mock_claim
    )

    fake_outcome = {
        "claim_facts": {"claim_id": str(mock_claim.id)},
        "result": {
            "review_report": {"overall_status": "completed"},
            "review_report_status": "completed",
            "human_review_required": True,
        },
        "error": None,
    }

    with (
        patch.object(agent_route, "SessionLocal", return_value=worker_session),
        patch("claimsage.workers.investigation_worker.run_investigation", return_value=fake_outcome) as mock_graph_run,
        patch("claimsage.workers.investigation_worker.finish_investigation") as mock_finish,
        patch.object(InvestigationWorker, "_dispatch_review_notification") as mock_notify,
    ):
        agent_route._run_investigation_background(
            investigation_id=inv_id,
            claim_id=mock_claim.id,
            employee_id=mock_claim.assigned_employee_id,
            task="Run background test.",
        )

        mock_graph_run.assert_called_once()
        mock_finish.assert_called_once_with(
            worker_session,
            investigation=mock_run,
            state=fake_outcome,
        )
        assert mock_notify.call_count == 2


def test_run_investigation_background_records_failure_on_exception(
    mock_claim: Claim,
) -> None:
    """Worker catches exceptions and safely records sanitized failure details."""
    inv_id = uuid4()
    mock_run = MagicMock()
    mock_run.id = inv_id

    worker_session = MagicMock()
    worker_session.__enter__.return_value = worker_session
    worker_session.get.side_effect = lambda model, obj_id: (
        mock_run if model is InvestigationRun else mock_claim
    )

    with (
        patch.object(agent_route, "SessionLocal", return_value=worker_session),
        patch(
            "claimsage.workers.investigation_worker.run_investigation",
            side_effect=RuntimeError("LLM API timeout"),
        ),
        patch("claimsage.workers.investigation_worker.fail_investigation") as mock_fail,
    ):
        agent_route._run_investigation_background(
            investigation_id=inv_id,
            claim_id=mock_claim.id,
            employee_id=mock_claim.assigned_employee_id,
            task="Failure test.",
        )

        mock_fail.assert_called_once_with(
            worker_session,
            investigation=mock_run,
            failure_type="RuntimeError",
            state=None,
        )


def test_get_investigation_result_endpoint(
    mock_employee: Employee,
    mock_claim: Claim,
) -> None:
    """GET /investigations/{id}/result returns the bounded InvestigationResponse."""
    inv_id = uuid4()
    mock_run = MagicMock()
    mock_run.id = inv_id
    mock_run.worker_id = "test-worker"
    mock_run.status = "completed"
    mock_run.failure_type = None
    mock_run.state_snapshot = {
        "claim_facts": {"claim_id": str(mock_claim.id)},
        "result": {
            "review_report": {"overall_status": "completed"},
        },
        "error": None,
    }

    session = MagicMock()

    with patch.object(
        investigations_route,
        "_get_authorized_investigation",
        return_value=mock_run,
    ):
        result = investigations_route.get_investigation_result(
            investigation_id=inv_id,
            employee=mock_employee,
            session=session,
        )

        assert isinstance(result, InvestigationResponse)
        assert result.investigation_id == inv_id
        assert result.execution_status == "completed"
        assert result.status == "completed"
        assert result.result["review_report"]["overall_status"] == "completed"
        assert result.error is None
