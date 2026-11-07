"""Pydantic schemas for health insurance policy administration."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class PolicyCoverageCreateRequest(BaseModel):
    """Request to create a structured policy coverage term."""

    model_config = ConfigDict(extra="forbid")

    coverage_name: str = Field(min_length=1, max_length=150)
    coverage_category: str = Field(default="inpatient", min_length=1, max_length=50)
    benefit_limit: Decimal | None = Field(default=None, ge=Decimal("0.00"))
    deductible: Decimal | None = Field(default=None, ge=Decimal("0.00"))
    co_pay_percentage: Decimal | None = Field(
        default=None,
        ge=Decimal("0.00"),
        le=Decimal("100.00"),
    )
    waiting_period_days: int | None = Field(default=None, ge=0)
    description: str | None = None
    is_optional: bool = False

    @field_validator("coverage_name", "coverage_category")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped


class PolicyCoverageResponse(BaseModel):
    """Structured policy coverage term details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    coverage_name: str
    coverage_category: str
    benefit_limit: Decimal | None = None
    deductible: Decimal | None = None
    co_pay_percentage: Decimal | None = None
    waiting_period_days: int | None = None
    description: str | None = None
    is_optional: bool
    created_at: datetime


class PolicyExclusionCreateRequest(BaseModel):
    """Request to create an explicit policy exclusion."""

    model_config = ConfigDict(extra="forbid")

    exclusion_code: str | None = Field(default=None, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    waiting_period_months: int | None = Field(default=None, ge=0)
    exclusion_type: Literal[
        "permanent",
        "waiting_period",
        "condition_based",
        "specified_illness",
        "other",
    ] = "permanent"

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped

    @field_validator("exclusion_code")
    @classmethod
    def strip_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None


class PolicyExclusionResponse(BaseModel):
    """Explicit policy exclusion details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    exclusion_code: str | None = None
    title: str
    description: str
    waiting_period_months: int | None = None
    exclusion_type: str
    created_at: datetime


class PolicyCreateRequest(BaseModel):
    """Administrative request to create a structured policy record."""

    model_config = ConfigDict(extra="forbid")

    policy_identifier: str = Field(min_length=1, max_length=150)
    insurer_name: str = Field(min_length=1, max_length=150)
    product_name: str = Field(min_length=1, max_length=200)
    insurance_type: Literal["health", "auto", "property"] = "health"
    policy_version: str = Field(default="v1.0", min_length=1, max_length=100)
    effective_from: date
    effective_to: date | None = None
    source_url: str | None = None
    supported_claim_types: list[str] = Field(default=["health"], min_length=1)
    coverages: list[PolicyCoverageCreateRequest] = Field(default_factory=list)
    exclusions: list[PolicyExclusionCreateRequest] = Field(default_factory=list)

    @field_validator("policy_identifier", "insurer_name", "product_name", "policy_version")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped

    @model_validator(mode="after")
    def validate_dates(self) -> "PolicyCreateRequest":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be earlier than effective_from.")
        return self


class PolicyUpdateRequest(BaseModel):
    """Request to update policy metadata, version, or effective dates."""

    model_config = ConfigDict(extra="forbid")

    policy_identifier: str | None = Field(default=None, max_length=150)
    insurer_name: str | None = Field(default=None, max_length=150)
    product_name: str | None = Field(default=None, max_length=200)
    insurance_type: Literal["health", "auto", "property"] | None = None
    policy_version: str | None = Field(default=None, max_length=100)
    effective_from: date | None = None
    effective_to: date | None = None
    source_url: str | None = None
    status: Literal["uploaded", "processing", "processed", "failed"] | None = None
    supported_claim_types: list[str] | None = None

    @field_validator("policy_identifier", "insurer_name", "product_name", "policy_version")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be blank.")
        return stripped

    @model_validator(mode="after")
    def validate_dates(self) -> "PolicyUpdateRequest":
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot be earlier than effective_from.")
        return self


class PolicySummaryResponse(BaseModel):
    """Compact summary of a policy for list and search views."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    policy_identifier: str
    insurer_name: str | None = None
    product_name: str | None = None
    insurance_type: str | None = None
    policy_version: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: str
    has_document_attached: bool = False
    chunk_count: int = 0
    clause_count: int = 0
    coverage_count: int = 0
    exclusion_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PolicyDetailResponse(PolicySummaryResponse):
    """Comprehensive policy details including coverages, exclusions, and applicability."""

    filename: str | None = None
    file_size_bytes: int = 0
    source_url: str | None = None
    supported_claim_types: list[str] = Field(default_factory=list)
    coverages: list[PolicyCoverageResponse] = Field(default_factory=list)
    exclusions: list[PolicyExclusionResponse] = Field(default_factory=list)
    linked_claims_count: int = 0


class PolicyClaimLinkRequest(BaseModel):
    """Request to associate an insurance claim with a policy."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID


class PolicyClaimLinkResponse(BaseModel):
    """Confirmation of policy-to-claim association."""

    policy_id: UUID
    claim_id: UUID
    claim_number: str
    policy_identifier: str
    insurer_name: str | None = None
    product_name: str | None = None
    linked_at: datetime
