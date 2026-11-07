"""Validated application configuration."""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _should_disable_dotenv() -> bool:
    return (
        os.environ.get("CLAIMSAGE_DISABLE_DOTENV") == "1"
        or os.environ.get("APP_ENV", "").strip().casefold() == "test"
    )


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=None if _should_disable_dotenv() else PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "ClaimSage"
    app_env: Literal["development", "test", "production"] = "development"

    # LLM provider configuration.
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str | None = Field(default=None)
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_model: str = Field(default="gemini-2.5-flash", min_length=1)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    groq_timeout_seconds: float = Field(default=60.0, gt=0.0, le=300.0)
    groq_max_input_tokens: int = Field(default=24000, ge=1000, le=100000)
    groq_max_output_tokens: int = Field(default=4096, ge=128, le=8192)
    groq_tokenizer_encoding: str = Field(default="o200k_harmony", min_length=1)
    groq_max_retries: int = Field(default=3, ge=0, le=10)
    groq_max_retry_delay_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    groq_concurrency_limit: int = Field(default=2, ge=1, le=10)
    groq_pacing_delay_seconds: float = Field(default=16.0, ge=0.0, le=30.0)

    email_backend: Literal["sandbox", "smtp"] = "sandbox"
    email_smtp_host: str | None = None
    email_smtp_port: int = Field(default=587, ge=1, le=65535)
    email_smtp_username: SecretStr | None = Field(default=None, repr=False)
    email_smtp_password: SecretStr | None = Field(default=None, repr=False)
    email_from_address: str = "claimsage-noreply@example.invalid"
    email_app_base_url: str = "http://localhost:5173"

    database_url: str = Field(
        default=(
            "postgresql+psycopg://claimsage_app:"
            "change-this-local-password@127.0.0.1:5432/claimsage"
        ),
        repr=False,
    )

    jwt_secret_key: SecretStr = Field(
        default=SecretStr("insecure-jwt-secret-key-for-dev-only-32chars"),
        repr=False,
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)

    # Security & Networking
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:8080", "http://127.0.0.1:8080"],
    )
    rate_limit_enabled: bool = True
    rate_limit_default_per_minute: int = Field(default=120, ge=10, le=10000)

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

    # Object storage configuration.
    storage_backend: Literal["s3", "in_memory"] = "s3"
    storage_endpoint_url: str | None = None
    storage_bucket_name: str = Field(
        default="claimsage-documents",
        min_length=3,
        max_length=63,
    )
    storage_region: str = "us-east-1"
    storage_access_key: SecretStr | None = Field(default=None, repr=False)
    storage_secret_key: SecretStr | None = Field(default=None, repr=False)
    storage_use_ssl: bool = False
    storage_auto_create_bucket: bool = True
    storage_server_side_encryption: str | None = Field(default=None)
    storage_kms_key_id: SecretStr | None = Field(default=None, repr=False)

    @field_validator("gemini_model")
    @classmethod
    def validate_gemini_model(cls, value: str) -> str:
        cleaned = value.strip()
        if (
            not cleaned
            or any(character.isspace() for character in cleaned)
            or "\r" in cleaned
            or "\n" in cleaned
        ):
            raise ValueError("GEMINI_MODEL must be a valid model identifier.")
        return cleaned

    @field_validator("email_from_address")
    @classmethod
    def validate_email_sender(cls, value: str) -> str:
        if not re.fullmatch(r"[^@\s\r\n]+@[^@\s\r\n]+", value):
            raise ValueError("EMAIL_FROM_ADDRESS must be a valid email address.")
        return value

    @field_validator("email_smtp_host")
    @classmethod
    def validate_smtp_host(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip()
            or any(character.isspace() for character in value)
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("EMAIL_SMTP_HOST must be a valid host name.")
        return value

    @model_validator(mode="after")
    def validate_runtime_configuration(self) -> "Settings":
        """Fail closed on unsafe runtime and credential configuration."""

        try:
            database_url = make_url(self.database_url)
        except (ArgumentError, TypeError, ValueError):
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL.") from None

        if database_url.get_backend_name() != "postgresql":
            raise ValueError("DATABASE_URL must use PostgreSQL.")
        if self.app_env == "test" and database_url.database != "claimsage_test":
            raise ValueError(
                "APP_ENV=test requires DATABASE_URL to target claimsage_test."
            )
        if (
            self.app_env == "production"
            and database_url.database == "claimsage_test"
        ):
            raise ValueError(
                "Production configuration must not target claimsage_test."
            )

        jwt_secret = self.jwt_secret_key.get_secret_value()
        if len(jwt_secret) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must contain at least 32 characters."
            )
        insecure_jwt_defaults = {
            "test-jwt-secret-key-that-is-at-least-32-bytes-long",
            "change-this-jwt-secret-key-minimum-32-chars",
            "your-super-secret-jwt-key-change-me",
            "insecure-jwt-secret-key-for-dev-only-32chars",
        }
        if self.app_env == "production" and jwt_secret in insecure_jwt_defaults:
            raise ValueError(
                "Production environment must not use an insecure default JWT_SECRET_KEY."
            )

        groq_api_key = (
            self.groq_api_key.get_secret_value().strip()
            if self.groq_api_key is not None
            else ""
        )
        if self.app_env == "production" and not groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is required in production configuration."
            )

        base_url = urlsplit(self.email_app_base_url)
        if (
            base_url.scheme not in {"https", "http"}
            or not base_url.hostname
            or base_url.username is not None
            or base_url.password is not None
            or base_url.query
            or base_url.fragment
            or (self.app_env == "production" and base_url.scheme != "https")
        ):
            raise ValueError(
                "EMAIL_APP_BASE_URL must be a safe application URL."
            )
        if self.email_backend == "smtp" and (
            not self.email_smtp_host or "@" not in self.email_from_address
        ):
            raise ValueError(
                "SMTP host and sender address are required for SMTP delivery."
            )
        if (
            (self.email_smtp_username is None)
            != (self.email_smtp_password is None)
        ):
            raise ValueError(
                "SMTP username and password must be configured together."
            )
        if (
            (self.storage_access_key is None)
            != (self.storage_secret_key is None)
        ):
            raise ValueError(
                "Storage access key and secret key must be configured together."
            )
        if self.app_env == "production" and self.storage_backend == "s3":
            if not self.storage_use_ssl:
                raise ValueError(
                    "Production object storage must enforce SSL/TLS (STORAGE_USE_SSL=true)."
                )
            if self.storage_endpoint_url is not None:
                parsed_storage_endpoint = urlsplit(self.storage_endpoint_url)
                if parsed_storage_endpoint.scheme != "https":
                    raise ValueError(
                        "Production object storage endpoint must use HTTPS."
                    )

        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    if _should_disable_dotenv():
        return Settings(_env_file=None)
    return Settings()
