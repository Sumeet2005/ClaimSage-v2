
"""HTTP tests for ClaimSage authentication."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from claimsage.db.models import AuditEvent, Employee, EmployeeRole
from claimsage.db.session import SessionLocal
from claimsage.main import app
from claimsage.services.auth import hash_password

TEST_PASSWORD = "TestPassword2026!Secure"


@pytest.fixture
def test_employee() -> Generator[Employee, None, None]:
    """Create and clean up a synthetic employee for authentication tests."""
    email = f"auth-test-{uuid4().hex}@claimsage.local"
    employee = Employee(
        email=email,
        display_name="Authentication Test Employee",
        password_hash=hash_password(TEST_PASSWORD),
        role=EmployeeRole.CLAIMS_ADJUSTER,
        team_id="test-team",
    )

    with SessionLocal.begin() as session:
        session.add(employee)
        session.flush()
        employee_id = employee.id

    try:
        yield employee
    finally:
        with SessionLocal.begin() as session:
            session.execute(
                delete(AuditEvent).where(
                    AuditEvent.actor_employee_id == employee_id
                )
            )
            session.execute(
                delete(Employee).where(Employee.id == employee_id)
            )


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the API."""
    return TestClient(app)


def test_login_with_valid_credentials_returns_token(
    client: TestClient,
    test_employee: Employee,
) -> None:
    """Valid credentials should return a Bearer token."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": test_employee.email, "password": TEST_PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


def test_login_with_wrong_password_is_rejected(
    client: TestClient,
    test_employee: Employee,
) -> None:
    """Incorrect passwords should return a generic 401 response."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": test_employee.email,
            "password": "WrongPassword2026!",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_unknown_email_has_same_login_error(client: TestClient) -> None:
    """Unknown accounts should not be distinguishable from wrong passwords."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": f"unknown-{uuid4().hex}@claimsage.local",
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


def test_me_rejects_missing_token(client: TestClient) -> None:
    """Protected endpoints should reject requests without a token."""
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_rejects_invalid_token(client: TestClient) -> None:
    """Protected endpoints should reject malformed tokens."""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.token.value"},
    )

    assert response.status_code == 401


def test_me_returns_current_employee_details(
    client: TestClient,
    test_employee: Employee,
) -> None:
    """A valid token should return employee details loaded from the database."""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": test_employee.email, "password": TEST_PASSWORD},
    )
    assert login_response.status_code == 200

    token = login_response.json()["access_token"]
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == test_employee.email
    assert body["display_name"] == "Authentication Test Employee"
    assert body["role"] == "claims_adjuster"
    assert body["team_id"] == "test-team"
