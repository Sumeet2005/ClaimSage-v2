
"""ClaimSage API application."""

from fastapi import FastAPI

from claimsage.api.routes.auth import router as auth_router
from claimsage.api.routes.claims import router as claims_router

app = FastAPI(
    title="ClaimSage API",
    description="Secure AI assistant for insurance employees.",
    version="0.1.0",
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(claims_router, prefix="/api/v1")


@app.get("/health/live", tags=["Health"])
def liveness_check() -> dict[str, str]:
    """Report whether the API process is running."""
    return {
        "status": "ok",
        "service": "claimsage-api",
    }
