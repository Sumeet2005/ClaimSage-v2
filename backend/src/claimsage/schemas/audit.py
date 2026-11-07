"""Pydantic schemas for Enterprise Audit Logging and Activity Tracking."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditEventResponse(BaseModel):
    """Sanitized, attributed audit event item for timeline displays."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_type: str
    actor_id: str | None = None
    actor_name: str
    actor_employee_id: UUID | None = None
    claim_id: UUID | None = None
    investigation_id: UUID | None = None
    event_category: str
    action: str
    outcome: str
    resource_type: str
    resource_id: str | None = None
    correlation_id: str | None = None
    details: str | None = None
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AuditTimelineResponse(BaseModel):
    """Paginated collection of audit timeline events."""

    items: list[AuditEventResponse]
    total_count: int
    limit: int
    offset: int
