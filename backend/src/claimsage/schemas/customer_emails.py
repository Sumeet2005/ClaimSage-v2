"""Pydantic schemas for Customer Email communications and lifecycle."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

CustomerEmailStatus = Literal[
    "drafted",
    "approved",
    "queued",
    "sent",
    "bounced",
    "replied",
    "failed",
]

CustomerEmailEventType = Literal[
    "claim_received",
    "investigation_completed",
    "human_review_required",
    "additional_evidence_required",
    "review_completed",
]


class CustomerEmailDraftRequest(BaseModel):
    """Request to create an email draft awaiting human approval."""

    event_type: CustomerEmailEventType
    recipient_email: EmailStr
    recipient_name: str = Field(min_length=1, max_length=200)
    subject: str | None = Field(default=None, max_length=255)
    body_text: str | None = None
    body_html: str | None = None
    requested_documents: list[str] | None = None
    follow_up_days: int = Field(default=7, ge=1, le=90)


class CustomerEmailUpdateRequest(BaseModel):
    """Request to update a drafted email before approval."""

    subject: str | None = Field(default=None, max_length=255)
    body_text: str | None = None
    body_html: str | None = None

    @field_validator("subject")
    @classmethod
    def sanitize_subject(cls, value: str | None) -> str | None:
        if value is not None:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("Subject cannot be empty if provided.")
            return cleaned
        return None


class CustomerEmailApprovalRequest(BaseModel):
    """Request to approve an email for dispatch."""

    notes: str | None = Field(default=None, max_length=1000)


class CustomerEmailResponse(BaseModel):
    """Full detail of a customer email communication."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    investigation_id: UUID | None = None
    event_type: str
    recipient_email: str
    recipient_name: str
    sender_email: str
    subject: str
    body_text: str
    body_html: str
    template_key: str
    status: CustomerEmailStatus
    approved_by_employee_id: UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    secure_upload_url: str | None = None
    follow_up_deadline: datetime | None = None
    reminder_sent_at: datetime | None = None
    idempotency_key: str
    attempt_count: int
    max_attempts: int
    last_error_type: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CustomerEmailSummary(BaseModel):
    """Summary of a customer email communication for listings."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    investigation_id: UUID | None = None
    event_type: str
    recipient_email: str
    recipient_name: str
    subject: str
    status: CustomerEmailStatus
    approved_by_employee_id: UUID | None = None
    approved_at: datetime | None = None
    secure_upload_url: str | None = None
    follow_up_deadline: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime


class EmailFollowUpListItem(BaseModel):
    """Unified email follow-up item representing customer emails and system deliveries."""

    id: UUID
    source_type: str
    claim_id: UUID | None = None
    claim_number: str | None = None
    claimant_name: str | None = None
    investigation_id: UUID | None = None
    event_type: str
    recipient_email: str | None = None
    recipient_name: str | None = None
    subject: str | None = None
    message_preview: str | None = None
    status: str
    has_secure_upload: bool = False
    secure_upload_url: str | None = None
    follow_up_deadline: datetime | None = None
    attempt_count: int = 0
    last_error_type: str | None = None
    created_at: datetime
    delivered_at: datetime | None = None
