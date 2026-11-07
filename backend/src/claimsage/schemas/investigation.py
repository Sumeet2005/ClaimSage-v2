"""Typed API schemas for persistent investigations and human review."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ClaimDomain = Literal["auto", "health", "other"]
InvestigationStatus = Literal["running", "completed", "incomplete", "failed"]
HumanReviewStatus = Literal[
    "pending",
    "approved",
    "needs_additional_documents",
    "returned_for_investigation",
    "escalated",
    "reviewed",
    "needs_follow_up",
]
ReviewDecision = Literal[
    "approved",
    "needs_additional_documents",
    "returned_for_investigation",
    "escalated",
    "reviewed",
    "needs_follow_up",
]
ReportStatus = Literal["completed", "incomplete", "unavailable", "skipped"]
EvidenceSufficiency = Literal[
    "sufficient_for_analysis",
    "insufficient_evidence",
    "undetermined",
]


class InvestigationSummary(BaseModel):
    """Concise persisted investigation metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    claim_domain: ClaimDomain
    status: InvestigationStatus
    current_stage: str | None
    human_review_status: HumanReviewStatus
    report_status: ReportStatus | None = None
    evidence_sufficiency: EvidenceSufficiency | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class InvestigationFindingResponse(BaseModel):
    """Persisted specialist finding with source provenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    specialist: str
    finding_type: str
    finding_data: dict[str, object]
    severity: str | None
    confidence: str | None
    evidence_references: list[dict[str, object]]
    policy_references: list[dict[str, object]]
    created_at: datetime


class InvestigationDetail(InvestigationSummary):
    """Authorized investigation state and its persisted findings."""

    task: str
    failure_type: str | None
    state_snapshot: dict[str, object]
    findings: list[InvestigationFindingResponse]


class InvestigationReportResponse(BaseModel):
    """Report payload, including unavailable/incomplete status and limits."""

    id: UUID
    investigation_id: UUID
    status: ReportStatus
    report_data: dict[str, object] | None
    limitations: list[str]
    human_review_required: Literal[True] = True
    created_at: datetime
    updated_at: datetime


class InvestigationReviewRequest(BaseModel):
    """Non-dispositive human review record."""

    decision: ReviewDecision
    notes: str | None = Field(default=None, max_length=4000)


class InvestigationReviewResponse(BaseModel):
    """Authenticated reviewer attribution and submitted review."""

    id: UUID
    investigation_id: UUID
    reviewer_employee_id: UUID
    reviewer_name: str
    decision: ReviewDecision
    notes: str | None
    created_at: datetime


class NotificationDeliveryResponse(BaseModel):
    """Safe delivery status without recipient or message contents."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: Literal[
        "claim_received",
        "investigation_completed",
        "human_review_required",
        "additional_evidence_required",
        "review_completed",
    ]
    status: Literal[
        "pending",
        "sending",
        "delivered",
        "sandboxed",
        "failed",
        "drafted",
    ]
    attempt_count: int = 0
    last_error_type: str | None = None
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None = None
    recipient_email: str | None = None
    recipient_name: str | None = None
    subject: str | None = None
    message: str | None = None
    secure_upload_url: str | None = None
    is_draft: bool = False
