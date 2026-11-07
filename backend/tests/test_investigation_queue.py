"""Tests for PostgreSQL-backed durable investigation queue, worker claiming, and leasing."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from claimsage.api.routes import agent as agent_route
from claimsage.db.models import Claim, Employee, EmployeeRole, InvestigationRun
from claimsage.schemas.agent import InvestigationRequest, InvestigationResponse
from claimsage.services.investigation_persistence import (
    create_investigation_run,
    finish_investigation,
    persist_progress,
)
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
        claim_number="CLM-TEST-999",
        claimant_name="Alice Smith",
        claim_type="Health",
        policy_identifier="POL-999",
        status="under_review",
        assigned_employee_id=mock_employee.id,
    )


def test_durable_job_creation(mock_claim: Claim, mock_employee: Employee) -> None:
    """create_investigation_run creates a durable queued job with attempt tracking."""
    session = MagicMock()
    estimate_id = uuid4()

    run = create_investigation_run(
        session,
        claim=mock_claim,
        employee_id=mock_employee.id,
        task="Investigate billing records.",
        repair_estimate_document_id=estimate_id,
        max_attempts=3,
    )

    assert run.status == "running"
    assert run.current_stage == "queued"
    assert run.attempt_count == 0
    assert run.max_attempts == 3
    assert run.repair_estimate_document_id == estimate_id
    assert session.commit.called


def test_worker_claims_eligible_job() -> None:
    """Worker claims queued job with atomic row lock, worker ID, and lease."""
    worker = InvestigationWorker(worker_id="worker-node-1", lease_duration_seconds=120)
    session = MagicMock()

    mock_run = MagicMock()
    mock_run.id = uuid4()
    mock_run.status = "running"
    mock_run.current_stage = "queued"
    mock_run.attempt_count = 0
    mock_run.max_attempts = 3
    mock_run.lease_expires_at = None

    session.scalar.return_value = mock_run

    job_id = worker.claim_next_job(session)

    assert job_id == mock_run.id
    assert mock_run.worker_id == "worker-node-1"
    assert mock_run.attempt_count == 1
    assert mock_run.current_stage == "starting"
    assert mock_run.lease_expires_at is not None
    session.commit.assert_called_once()


def test_worker_returns_none_when_queue_empty() -> None:
    """Worker returns None and rolls back when no eligible jobs exist."""
    worker = InvestigationWorker(worker_id="worker-node-1")
    session = MagicMock()
    session.scalar.return_value = None

    job_id = worker.claim_next_job(session)

    assert job_id is None
    session.rollback.assert_called_once()


def test_worker_recovers_expired_lease_within_retry_limit() -> None:
    """Worker reclaims a job whose worker crashed (lease expired) if retries remain."""
    worker = InvestigationWorker(worker_id="worker-node-2", lease_duration_seconds=120)
    session = MagicMock()

    expired_run = MagicMock()
    expired_run.id = uuid4()
    expired_run.status = "running"
    expired_run.current_stage = "policy_analyst"
    expired_run.worker_id = "crashed-worker-old"
    expired_run.attempt_count = 1
    expired_run.max_attempts = 3
    expired_run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)

    session.scalar.return_value = expired_run

    job_id = worker.claim_next_job(session)

    assert job_id == expired_run.id
    assert expired_run.worker_id == "worker-node-2"
    assert expired_run.attempt_count == 2
    assert expired_run.lease_expires_at > datetime.now(UTC)
    session.commit.assert_called_once()


def test_worker_reaps_expired_job_exceeding_max_retries() -> None:
    """reap_expired_jobs marks runs with exceeded retries as failed."""
    worker = InvestigationWorker(worker_id="worker-node-1")
    session = MagicMock()

    dead_job = MagicMock()
    dead_job.id = uuid4()
    dead_job.status = "running"
    dead_job.attempt_count = 3
    dead_job.max_attempts = 3
    dead_job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)

    session.scalars.return_value.all.return_value = [dead_job]

    reaped_count = worker.reap_expired_jobs(session)

    assert reaped_count == 1
    assert dead_job.status == "failed"
    assert dead_job.failure_type == "MaxRetriesExceeded"
    assert dead_job.current_stage is None
    assert dead_job.lease_expires_at is None
    session.commit.assert_called_once()


def test_heartbeat_updates_lease_expiration() -> None:
    """persist_progress updates lease_expires_at to maintain worker heartbeat."""
    session = MagicMock()
    mock_run = MagicMock()
    mock_run.lease_expires_at = None

    now = datetime.now(UTC)
    persist_progress(
        session,
        investigation=mock_run,
        stage="risk_anomaly_agent",
        state={"claim_facts": {}},
        lease_seconds=180,
    )

    assert mock_run.current_stage == "risk_anomaly_agent"
    assert mock_run.lease_expires_at is not None
    assert mock_run.lease_expires_at > now + timedelta(seconds=170)
    session.commit.assert_called_once()


def test_finish_investigation_clears_lease() -> None:
    """finish_investigation clears worker leasing metadata upon completion."""
    session = MagicMock()
    mock_run = MagicMock()
    mock_run.worker_id = "worker-1"
    mock_run.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)

    fake_state = {
        "result": {
            "review_report": {"overall_status": "completed"},
            "review_report_status": "completed",
            "limitations": [],
        },
        "error": None,
    }

    with patch("claimsage.services.investigation_persistence.is_investigation_complete", return_value=True):
        finish_investigation(session, investigation=mock_run, state=fake_state)

    assert mock_run.status == "completed"
    assert mock_run.current_stage is None
    assert mock_run.worker_id is None
    assert mock_run.lease_expires_at is None
    session.commit.assert_called()


def test_investigate_claim_api_does_not_execute_in_process(
    mock_employee: Employee,
    mock_claim: Claim,
) -> None:
    """API endpoint returns 202 Accepted without running the graph in-process."""
    session = MagicMock()
    session.scalar.return_value = None  # No running investigation

    mock_run = MagicMock()
    mock_run.id = uuid4()
    mock_run.status = "running"
    mock_run.current_stage = "queued"

    with patch.object(agent_route, "get_authorized_claim", return_value=mock_claim), \
         patch.object(agent_route, "create_investigation_run", return_value=mock_run), \
         patch.object(agent_route, "run_investigation") as mock_run_graph:

        request = InvestigationRequest(
            claim_id=mock_claim.id,
            task="Durable queue test.",
        )

        response = agent_route.investigate_claim(
            request=request,
            employee=mock_employee,
            session=session,
        )

        assert isinstance(response, InvestigationResponse)
        assert response.investigation_id == mock_run.id
        assert response.execution_status == "running"
        # Verify the LangGraph workflow was NOT invoked inside the API handler!
        mock_run_graph.assert_not_called()


def test_investigate_claim_preserves_legitimate_long_running_job(
    mock_employee: Employee,
    mock_claim: Claim,
) -> None:
    """An active investigation with recent heartbeat is NOT killed if created > 15m ago."""
    session = MagicMock()

    active_run = MagicMock()
    active_run.id = uuid4()
    active_run.status = "running"
    # Created 25 minutes ago, but lease expires in 90 seconds (active heartbeat!)
    active_run.created_at = datetime.now(UTC) - timedelta(minutes=25)
    active_run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=90)
    active_run.updated_at = datetime.now(UTC) - timedelta(seconds=30)
    session.scalar.return_value = active_run

    with patch.object(agent_route, "get_authorized_claim", return_value=mock_claim):
        request = InvestigationRequest(
            claim_id=mock_claim.id,
            task="Concurrent request while actively running.",
        )

        with pytest.raises(HTTPException) as exc_info:
            agent_route.investigate_claim(
                request=request,
                employee=mock_employee,
                session=session,
            )

        assert exc_info.value.status_code == 409
        assert "already in progress" in exc_info.value.detail
        # Must NOT be marked failed!
        assert active_run.status == "running"


def test_worker_graceful_shutdown() -> None:
    """Worker stops cleanly when request_stop() is called."""
    worker = InvestigationWorker(worker_id="test-worker")
    assert not worker._stopping
    worker.request_stop()
    assert worker._stopping
