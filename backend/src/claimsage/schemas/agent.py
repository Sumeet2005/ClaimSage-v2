"""Request and response schemas for ClaimSage investigations."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class InvestigationRequest(BaseModel):
    """Request to investigate an accessible claim."""

    claim_id: UUID
    task: str = Field(min_length=1, max_length=1000)
    repair_estimate_document_id: UUID | None = None

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Investigation task cannot be blank.")
        return value


class InvestigationResponse(BaseModel):
    """Bounded output from a ClaimSage investigation."""

    investigation_id: UUID | None = None
    execution_status: Literal["queued", "running", "completed", "incomplete", "failed"] = "running"
    status: Literal["running", "completed", "incomplete", "failed"] | None = None
    claim_facts: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
