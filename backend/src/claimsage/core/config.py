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

    # LLM provider configuration.
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

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

    # Upload request limits.
    upload_max_request_bytes: int = Field(
        default=22 * 1024 * 1024,
        ge=1048576,
        le=52428800,
    )

    # PDF processing limits.
    pdf_max_pages: int = Field(default=100, ge=1, le=500)

    # Document OCR configuration.
    ocr_enabled: bool = True
    tesseract_cmd: str | None = Field(default=None, repr=False)
    ocr_language: str = Field(default="eng", min_length=1, max_length=32)
    ocr_dpi: int = Field(default=200, ge=100, le=400)
    ocr_max_pages: int = Field(default=100, ge=1, le=500)
    ocr_timeout_seconds: int = Field(default=30, ge=1, le=300)


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    settings = Settings()

    if settings.app_env.lower() != "development" and len(
        settings.jwt_secret_key.get_secret_value()
    ) < 32:
        raise ValueError("JWT_SECRET_KEY must contain at least 32 characters.")

    return settings
