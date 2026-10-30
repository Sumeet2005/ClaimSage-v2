"""Policy document API request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PolicyDocumentUploadResponse(BaseModel):
    """Response returned after a policy document upload."""

    document_id: UUID
    filename: str
    status: str
    chunk_count: int


class PolicyDocumentAccessGrantRequest(BaseModel):
    """Request to grant access to a team or a specific claim."""

    model_config = ConfigDict(extra="forbid")

    team_id: str | None = Field(default=None, min_length=1, max_length=100)
    claim_id: UUID | None = None

    @model_validator(mode="after")
    def validate_exactly_one_scope(self):
        """Require exactly one non-empty access scope."""

        has_team = self.team_id is not None
        has_claim = self.claim_id is not None

        if has_team == has_claim:
            raise ValueError(
                "Provide exactly one of team_id or claim_id."
            )

        if self.team_id is not None:
            self.team_id = self.team_id.strip()

            if not self.team_id:
                raise ValueError("team_id must not be empty.")

        return self


class PolicyDocumentAccessGrantResponse(BaseModel):
    """Response describing a policy document access grant."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    team_id: str | None
    claim_id: UUID | None
    granted_by_employee_id: UUID
    created_at: datetime
