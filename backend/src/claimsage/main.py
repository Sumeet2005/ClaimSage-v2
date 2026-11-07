"""ClaimSage API application."""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from claimsage.api.routes.agent import router as agent_router
from claimsage.api.routes.audit import router as audit_router
from claimsage.api.routes.auth import router as auth_router
from claimsage.api.routes.claims import router as claims_router
from claimsage.api.routes.customer_emails import router as customer_emails_router
from claimsage.api.routes.evidence import router as evidence_router
from claimsage.api.routes.investigations import router as investigations_router
from claimsage.api.routes.policies import router as policies_router
from claimsage.api.routes.system import router as system_router
from claimsage.core.config import get_settings
from claimsage.core.observability import CorrelationIdMiddleware, StructuredJsonFormatter
from claimsage.core.rate_limit import RateLimitMiddleware
from claimsage.core.upload_limits import UploadSizeLimitMiddleware

settings = get_settings()

# Initialize structured logging in production environments
if settings.app_env == "production":
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.INFO)

logger = logging.getLogger("claimsage.api")

app = FastAPI(
    title="ClaimSage API",
    description="Secure AI assistant for insurance employees.",
    version="0.1.0",
)

# Correlation ID middleware for end-to-end tracing
app.add_middleware(CorrelationIdMiddleware)

# Rate limiting middleware for DDoS and brute-force protection
app.add_middleware(
    RateLimitMiddleware,
    default_limit=settings.rate_limit_default_per_minute,
    enabled=settings.rate_limit_enabled and settings.app_env == "production",
)

# CORS middleware for secure web frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global unhandled exception handler to prevent sensitive traceback leakage
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None) or str(uuid4())
    logger.error(
        "Unhandled internal error during %s %s [correlation_id=%s]: %s",
        request.method,
        request.url.path,
        correlation_id,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred.",
            "correlation_id": correlation_id,
        },
    )

app.include_router(auth_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(evidence_router, prefix="/api/v1")
app.include_router(customer_emails_router, prefix="/api/v1")
app.include_router(claims_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(investigations_router, prefix="/api/v1")
app.include_router(policies_router, prefix="/api/v1")
app.include_router(system_router, prefix="/api/v1")


@app.get("/health/live", tags=["Health"])
def liveness_check() -> dict[str, str]:
    """Report whether the API process is running."""
    return {
        "status": "ok",
        "service": "claimsage-api",
    }


@app.get("/health/ready", tags=["Health"])
def readiness_check(response: Response) -> dict[str, str]:
    """Report whether application dependencies (database, queue, storage) are available."""
    from sqlalchemy import text
    from claimsage.db.session import SessionLocal
    from claimsage.services.storage import get_storage_service

    status_report = {
        "status": "ready",
        "service": "claimsage-api",
        "database": "connected",
        "queue": "ready",
        "storage": "connected",
    }
    is_ready = True

    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        status_report["database"] = f"unreachable: {exc}"
        is_ready = False

    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1 FROM investigation_runs LIMIT 1"))
    except Exception as exc:
        status_report["queue"] = f"unreachable: {exc}"
        is_ready = False

    try:
        storage = get_storage_service()
        storage.ensure_bucket_exists()
    except Exception as exc:
        status_report["storage"] = f"degraded: {exc}"

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        status_report["status"] = "not_ready"

    return status_report


# Enforce upload size before FastAPI parses multipart bodies.
app = UploadSizeLimitMiddleware(
    app,
    max_body_bytes=get_settings().upload_max_request_bytes,
)
