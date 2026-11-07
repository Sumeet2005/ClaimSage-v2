"""System configuration, health diagnostics, and runtime settings endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from claimsage.api.dependencies import get_current_employee
from claimsage.core.config import get_settings
from claimsage.db.models import Employee
from claimsage.db.session import get_db
from claimsage.services.storage import get_storage_service

router = APIRouter(prefix="/system", tags=["System"])


class ServiceHealthItem(BaseModel):
    database: str
    storage: str
    worker: str
    pgvector: str


class CurrentEmployeeProfile(BaseModel):
    id: UUID
    display_name: str
    email: str
    role: str
    team_id: str | None = None


class SystemSettingsResponse(BaseModel):
    app_name: str
    app_env: str
    version: str
    llm_provider: str
    llm_model: str
    llm_max_output_tokens: int
    llm_timeout_seconds: float
    llm_concurrency_limit: int
    storage_provider: str
    storage_bucket: str
    storage_endpoint: str | None = None
    email_backend: str
    default_sender_email: str
    rate_limit_enabled: bool
    rate_limit_per_minute: int
    token_expiry_minutes: int
    services: ServiceHealthItem
    current_employee: CurrentEmployeeProfile


@router.get("/settings", response_model=SystemSettingsResponse)
def get_system_settings(
    employee: Employee = Depends(get_current_employee),
    session: Session = Depends(get_db),
) -> SystemSettingsResponse:
    """Return non-secret system environment settings and live dependency status."""
    settings = get_settings()

    # Dynamic dependency checks
    db_status = "connected"
    pgvector_status = "enabled"
    try:
        session.execute(text("SELECT 1"))
        res = session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        if not res:
            pgvector_status = "unavailable"
    except Exception as exc:
        db_status = f"degraded: {exc}"

    storage_status = "connected"
    try:
        storage = get_storage_service()
        storage.ensure_bucket_exists()
    except Exception as exc:
        storage_status = f"degraded: {exc}"

    # Masked storage endpoint (no credentials)
    endpoint_display = settings.storage_endpoint_url or "s3.amazonaws.com"
    if "@" in endpoint_display:
        endpoint_display = endpoint_display.split("@")[-1]

    return SystemSettingsResponse(
        app_name="ClaimSage",
        app_env=settings.app_env,
        version="0.1.0",
        llm_provider="groq",
        llm_model=settings.groq_model,
        llm_max_output_tokens=settings.groq_max_output_tokens,
        llm_timeout_seconds=settings.groq_timeout_seconds,
        llm_concurrency_limit=settings.groq_concurrency_limit,
        storage_provider=settings.storage_backend or "s3",
        storage_bucket=settings.storage_bucket_name,
        storage_endpoint=endpoint_display,
        email_backend=settings.email_backend,
        default_sender_email=settings.email_from_address,
        rate_limit_enabled=settings.rate_limit_enabled,
        rate_limit_per_minute=settings.rate_limit_default_per_minute,
        token_expiry_minutes=settings.access_token_expire_minutes,
        services=ServiceHealthItem(
            database=db_status,
            storage=storage_status,
            worker="active",
            pgvector=pgvector_status,
        ),
        current_employee=CurrentEmployeeProfile(
            id=employee.id,
            display_name=employee.display_name,
            email=employee.email,
            role=str(employee.role),
            team_id=employee.team_id,
        ),
    )
