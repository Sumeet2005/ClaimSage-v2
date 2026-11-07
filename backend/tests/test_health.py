from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from claimsage.main import app

client = TestClient(app)


def test_liveness_endpoint_returns_success() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "claimsage-api",
    }


def test_readiness_endpoint_healthy() -> None:
    with (
        patch("claimsage.db.session.SessionLocal") as mock_session_local,
        patch("claimsage.services.storage.get_storage_service") as mock_storage,
    ):
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_storage.return_value.ensure_bucket_exists.return_value = True

        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert data["queue"] == "ready"
        assert data["storage"] == "connected"


def test_readiness_endpoint_queue_failure() -> None:
    with (
        patch("claimsage.db.session.SessionLocal") as mock_session_local,
        patch("claimsage.services.storage.get_storage_service") as mock_storage,
    ):
        mock_session = MagicMock()
        mock_session.execute.side_effect = [MagicMock(), Exception("Table not found")]
        mock_session_local.return_value.__enter__.return_value = mock_session
        mock_storage.return_value.ensure_bucket_exists.return_value = True

        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert "unreachable" in data["queue"]
