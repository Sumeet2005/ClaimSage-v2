"""Pydantic response schemas for insurance claims."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    policy_identifier: str | None = None
    insurer_name: str | None = None
    product_name: str | None = None
    loss_date: date | None = None


class ClaimCreateRequest(BaseModel):
    """Payload to create a new claim with authorization and audit tracking."""

    model_config = ConfigDict(extra="forbid")

    claim_number: str = Field(min_length=3, max_length=50)
    claimant_name: str = Field(min_length=1, max_length=200)
    claim_type: str = Field(min_length=1, max_length=100)
    summary: str | None = Field(default=None, max_length=2000)
    loss_date: date | None = None
    policy_identifier: str | None = Field(default=None, max_length=150)
    insurer_name: str | None = Field(default=None, max_length=150)
    product_name: str | None = Field(default=None, max_length=200)
    team_id: str | None = Field(default=None, max_length=100)
    assigned_employee_id: UUID | None = None

    @field_validator("claim_number", "claimant_name", "claim_type")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Field must not be blank.")
        return normalized

    @field_validator("policy_identifier", "insurer_name", "product_name", "team_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ClaimPolicyMetadataUpdate(BaseModel):
    """Source-verified policy identity, dates, and optional source labels."""

    model_config = ConfigDict(extra="forbid")

    policy_identifier: str = Field(min_length=1, max_length=150)
    insurer_name: str | None = Field(default=None, max_length=150)
    product_name: str | None = Field(default=None, max_length=200)
    loss_date: date
    verified_against_source: Literal[True]

    @field_validator("policy_identifier")
    @classmethod
    def normalize_policy_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Policy identifier must not be blank.")
        return normalized

    @field_validator("insurer_name", "product_name")
    @classmethod
    def normalize_optional_policy_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Insurer and product names must not be blank.")
        return normalized
