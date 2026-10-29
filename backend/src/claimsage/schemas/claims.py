
"""Pydantic response schemas for insurance claims."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClaimResponse(BaseModel):
    """Safe representation of a claim returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_number: str
    claimant_name: str
    claim_type: str
    status: str
    team_id: str | None
    summary: str | None
    created_at: datetime
