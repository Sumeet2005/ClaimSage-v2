"""Pydantic schemas for Human Review, finding revisions, and workflow actions."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

ReviewDecision = Literal[
    "approved",
    "needs_additional_documents",
    "returned_for_investigation",
    "escalated",
    "reviewed",
    "needs_follow_up",
]


class InvestigationReviewRequest(BaseModel):
    """Request to record an authorized human review decision."""

    decision: ReviewDecision
    notes: str | None = Field(default=None, max_length=4000)
    requested_documents: list[str] | None = Field(default=None)
    escalate_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("notes")
    @classmethod
    def sanitize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None


class InvestigationReviewResponse(BaseModel):
    """Response representing an attributed human review decision."""

    id: UUID
    investigation_id: UUID
    reviewer_employee_id: UUID
    reviewer_name: str
    decision: str
    notes: str | None = None
    created_at: datetime


class FindingEditRequest(BaseModel):
    """Request to record a versioned human modification to an AI finding."""

    edited_data: dict[str, Any]
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Edit reason must be at least 5 characters.")
        return cleaned


class FindingEditResponse(BaseModel):
    """Response representing an attributed human finding edit."""

    id: UUID
    finding_id: UUID
    investigation_id: UUID
    editor_employee_id: UUID
    editor_name: str
    original_data: dict[str, Any]
    edited_data: dict[str, Any]
    reason: str
    created_at: datetime
