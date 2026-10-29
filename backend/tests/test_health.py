
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
