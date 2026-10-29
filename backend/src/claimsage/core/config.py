"""Validated application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ClaimSage"
    app_env: str = "development"

    database_url: str = Field(
        default=(
            "postgresql+psycopg://claimsage_app:"
            "change-this-local-password@127.0.0.1:5432/claimsage"
        ),
        repr=False,
    )

    jwt_secret_key: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()

    if settings.app_env.lower() != "development" and len(
        settings.jwt_secret_key.get_secret_value()
    ) < 32:
        raise ValueError("JWT_SECRET_KEY must contain at least 32 characters.")

    return settings