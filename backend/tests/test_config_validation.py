"""Database-free application configuration validation tests."""

import pytest
from pydantic import ValidationError

from claimsage.core.config import Settings

_TEST_JWT_SECRET = "synthetic-test-signing-secret-32"
_TEST_DATABASE_URL = (
    "postgresql+psycopg://synthetic:synthetic@127.0.0.1/claimsage_test"
)


def build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": _TEST_DATABASE_URL,
        "jwt_secret_key": _TEST_JWT_SECRET,
        "groq_api_key": None,
    }
    values.update(overrides)
    if values["app_env"] == "production":
        values.setdefault(
            "email_app_base_url",
            "https://claims.example.invalid",
        )
    return Settings(_env_file=None, **values)


def test_test_environment_requires_isolated_database() -> None:
    with pytest.raises(ValidationError, match="requires DATABASE_URL"):
        build_settings(
            database_url=(
                "postgresql+psycopg://synthetic:synthetic@127.0.0.1/claimsage"
            )
        )


def test_jwt_secret_requires_minimum_length() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        build_settings(jwt_secret_key="synthetic-short")


def test_production_requires_groq_and_rejects_test_database() -> None:
    with pytest.raises(ValidationError, match="GROQ_API_KEY is required"):
        build_settings(
            app_env="production",
            database_url=(
                "postgresql+psycopg://synthetic:synthetic@db.example/claimsage_prod"
            ),
        )

    with pytest.raises(ValidationError, match="must not target claimsage_test"):
        build_settings(
            app_env="production",
            groq_api_key="synthetic-groq-placeholder",
        )


def test_valid_production_configuration_uses_placeholders_only() -> None:
    settings = build_settings(
        app_env="production",
        database_url=(
            "postgresql+psycopg://synthetic:synthetic@db.example/claimsage_prod"
        ),
        groq_api_key="synthetic-groq-placeholder",
    )

    assert settings.app_env == "production"


def test_smtp_configuration_requires_a_host_and_sender() -> None:
    with pytest.raises(ValidationError, match="SMTP host and sender address"):
        build_settings(email_backend="smtp")

    settings = build_settings(
        email_backend="smtp",
        email_smtp_host="smtp.example.invalid",
        email_from_address="claimsage@example.invalid",
    )
    assert settings.email_backend == "smtp"


def test_production_email_links_require_https() -> None:
    with pytest.raises(ValidationError, match="safe application URL"):
        build_settings(
            app_env="production",
            database_url="postgresql://test@db.example/claimsage_prod",
            groq_api_key="synthetic-groq-placeholder",
            email_app_base_url="http://claims.example.invalid",
        )
