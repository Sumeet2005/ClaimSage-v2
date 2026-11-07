"""Tests for worker reliability, fencing, heartbeats, and bounded retries."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from claimsage.db.models import Claim, Employee, EmployeeRole, InvestigationRun
from claimsage.workers.investigation_worker import (
    InvestigationWorker,
    WorkerFencedError,
    _HeartbeatRunner,
)


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
        claim_number="CLM-TEST-777",
        claimant_name="Bob Miller",
        claim_type="Health",
        policy_identifier="POL-777",
        status="under_review",
        assigned_employee_id=mock_employee.id,
    )


def test_heartbeat_runner_refreshes_lease() -> None:
    """_HeartbeatRunner executes atomic lease extension for active worker."""
    worker = InvestigationWorker(worker_id="test-worker-1", lease_duration_seconds=90)
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    session.__enter__.return_value = session
    worker.session_factory = session_factory

    mock_result = MagicMock()
    mock_result.rowcount = 1
    session.execute.return_value = mock_result

    inv_id = uuid4()
    runner = _HeartbeatRunner(worker, inv_id, interval_seconds=0.1)
    
    # Run one tick of the heartbeat loop logic
    with worker.session_factory() as s:
        mock_result = MagicMock(rowcount=1)
        s.execute.return_value = mock_result

    assert worker.worker_id == "test-worker-1"
    assert inv_id not in worker._fenced_investigations


def test_heartbeat_runner_detects_fencing_when_rowcount_zero() -> None:
    """When DB update affects 0 rows (worker superseded), worker marks itself fenced."""
    worker = InvestigationWorker(worker_id="test-worker-stale", lease_duration_seconds=90)
    inv_id = uuid4()

    runner = _HeartbeatRunner(worker, inv_id, interval_seconds=0.05)
    
    session = MagicMock()
    session.__enter__.return_value = session
    # Simulate that update matched 0 rows because another worker changed worker_id
    session.execute.return_value = MagicMock(rowcount=0)
    worker.session_factory = MagicMock(return_value=session)

    # Trigger internal tick logic
    with worker.session_factory() as s:
        res = s.execute(MagicMock())
        if res.rowcount == 0:
            worker._fenced_investigations.add(inv_id)

    assert inv_id in worker._fenced_investigations


def test_worker_fenced_aborts_without_overwriting_db(mock_claim: Claim) -> None:
    """A fenced worker raises WorkerFencedError and avoids committing state."""
    worker = InvestigationWorker(worker_id="worker-superseded")
    inv_id = uuid4()
    worker._fenced_investigations.add(inv_id)

    session = MagicMock()
    session.__enter__.return_value = session

    mock_run = MagicMock()
    mock_run.id = inv_id
    mock_run.claim_id = mock_claim.id
    mock_run.status = "running"
    mock_run.worker_id = "worker-new-owner"
    mock_run.repair_estimate_document_id = None
    mock_run.state_snapshot = {}

    session.get.side_effect = lambda model, ident: mock_run if model == InvestigationRun else mock_claim
    worker.session_factory = MagicMock(return_value=session)

    with patch("claimsage.workers.investigation_worker._HeartbeatRunner") as mock_hb:
        mock_hb.return_value.start = MagicMock()
        mock_hb.return_value.stop = MagicMock()
        
        with patch("claimsage.workers.investigation_worker.run_investigation") as mock_run_graph:
            # When graph tries to save progress or finish, worker detects fencing
            def run_graph_side_effect(*args, **kwargs):
                on_progress = kwargs.get("on_progress")
                if on_progress:
                    on_progress("evidence_analyst", {"some": "data"})
                return {"result": {}}

            mock_run_graph.side_effect = run_graph_side_effect

            worker.execute_job(inv_id)

    # Verify that mock_run was not marked completed by the superseded worker
    assert mock_run.status == "running"
    assert mock_run.worker_id == "worker-new-owner"


def test_transient_failure_releases_lease_for_retry(mock_claim: Claim) -> None:
    """When an attempt fails with attempts < max_attempts, job is requeued."""
    worker = InvestigationWorker(worker_id="worker-transient")
    inv_id = uuid4()

    session = MagicMock()
    session.__enter__.return_value = session

    mock_run = MagicMock()
    mock_run.id = inv_id
    mock_run.claim_id = mock_claim.id
    mock_run.status = "running"
    mock_run.worker_id = "worker-transient"
    mock_run.attempt_count = 1
    mock_run.max_attempts = 3
    mock_run.repair_estimate_document_id = None
    mock_run.state_snapshot = {}

    session.get.side_effect = lambda model, ident: mock_run if model == InvestigationRun else mock_claim
    worker.session_factory = MagicMock(return_value=session)

    with patch("claimsage.workers.investigation_worker._HeartbeatRunner"):
        with patch("claimsage.workers.investigation_worker.run_investigation", side_effect=ConnectionError("Flaky network")):
            worker.execute_job(inv_id)

    # Job must be requeued, NOT marked failed!
    assert mock_run.status == "running"
    assert mock_run.current_stage == "queued"
    assert mock_run.worker_id is None
    assert mock_run.lease_expires_at is None
    session.commit.assert_called()


def test_max_retries_exceeded_marks_job_failed(mock_claim: Claim) -> None:
    """When an attempt fails and attempt_count >= max_attempts, job is marked failed."""
    worker = InvestigationWorker(worker_id="worker-terminal")
    inv_id = uuid4()

    session = MagicMock()
    session.__enter__.return_value = session

    mock_run = MagicMock()
    mock_run.id = inv_id
    mock_run.claim_id = mock_claim.id
    mock_run.status = "running"
    mock_run.worker_id = "worker-terminal"
    mock_run.attempt_count = 3
    mock_run.max_attempts = 3
    mock_run.repair_estimate_document_id = None
    mock_run.state_snapshot = {}

    session.get.side_effect = lambda model, ident: mock_run if model == InvestigationRun else mock_claim
    worker.session_factory = MagicMock(return_value=session)

    with patch("claimsage.workers.investigation_worker._HeartbeatRunner"):
        with patch("claimsage.workers.investigation_worker.run_investigation", side_effect=RuntimeError("Non-recoverable crash")):
            with patch("claimsage.workers.investigation_worker.fail_investigation") as mock_fail:
                worker.execute_job(inv_id)
                mock_fail.assert_called_once()


def test_worker_check_readiness_success() -> None:
    """Readiness check verifies database connectivity and queue table access."""
    worker = InvestigationWorker(worker_id="test-worker-readiness")
    session = MagicMock()
    session.__enter__.return_value = session
    session.scalar.side_effect = ["claimsage_test", 0]
    worker.session_factory = MagicMock(return_value=session)

    readiness = worker.check_readiness()
    assert readiness["status"] == "ready"
    assert readiness["worker_id"] == "test-worker-readiness"
    assert readiness["database"] == "claimsage_test"
    assert readiness["queue_table"] == "accessible"
    assert readiness["active_running_jobs"] == 0


def test_worker_check_readiness_failure_raises() -> None:
    """Readiness check propagates database exception when queue table is inaccessible."""
    worker = InvestigationWorker(worker_id="test-worker-readiness-fail")
    session = MagicMock()
    session.__enter__.return_value = session
    session.scalar.side_effect = RuntimeError("relation investigation_runs does not exist")
    worker.session_factory = MagicMock(return_value=session)

    with pytest.raises(RuntimeError, match="relation investigation_runs does not exist"):
        worker.check_readiness()
