"""Shared fixtures for ClaimSage API tests."""

import os

if not os.environ.get("JWT_SECRET_KEY") or len(os.environ.get("JWT_SECRET_KEY", "")) < 32:
    os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-that-is-at-least-32-bytes-long"
if not os.environ.get("APP_ENV"):
    os.environ["APP_ENV"] = "test"
if not os.environ.get("CLAIMSAGE_DISABLE_DOTENV"):
    os.environ["CLAIMSAGE_DISABLE_DOTENV"] = "1"

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def pytest_sessionstart(session: pytest.Session) -> None:
    """Prevent tests from running unless explicitly configured for claimsage_test."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise pytest.UsageError(
            "Backend tests require DATABASE_URL to be explicitly set to "
            "the PostgreSQL claimsage_test database."
        )

    try:
        parsed_url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise pytest.UsageError(
            "Backend tests require a valid PostgreSQL DATABASE_URL "
            "targeting claimsage_test."
        ) from None

    if (
        parsed_url.get_backend_name() != "postgresql"
        or parsed_url.database != "claimsage_test"
    ):
        raise pytest.UsageError(
            "Backend tests require DATABASE_URL to target the PostgreSQL "
            "claimsage_test database."
        )


@pytest.fixture(autouse=True)
def configure_test_storage(monkeypatch: pytest.MonkeyPatch):
    """Provide isolated in-memory storage and clean settings cache for each test execution."""
    from claimsage.core.config import get_settings
    from claimsage.services.storage import InMemoryStorageService, set_storage_service

    monkeypatch.setenv("CLAIMSAGE_DISABLE_DOTENV", "1")
    get_settings.cache_clear()
    test_storage = InMemoryStorageService()
    set_storage_service(test_storage)
    monkeypatch.setenv("STORAGE_BACKEND", "in_memory")
    yield test_storage
    set_storage_service(None)
    get_settings.cache_clear()
