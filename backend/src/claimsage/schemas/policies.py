"""Policy document API request and response schemas."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def normalize_insurance_type(value: str) -> str:
    """Map the user-facing motor line to the existing auto taxonomy."""

    normalized = value.strip().casefold()
    return "auto" if normalized == "motor" else normalized


class PolicyDocumentUploadResponse(BaseModel):
    """Response returned after a policy document upload."""

    document_id: UUID
    filename: str
    status: Literal["pending", "processing", "ready", "failed"]
    chunk_count: int
    clause_count: int = 0
    processing_error: str | None = None
    insurer_name: str | None = None
    product_name: str | None = None
    source_url: str | None = None
    policy_identifier: str | None = None
    insurance_type: str | None = None
    policy_version: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    storage_status: str | None = None


class PolicyClauseVerificationRequest(BaseModel):
    """Human review decision for one source-traceable clause."""

    model_config = ConfigDict(extra="forbid")

    verification_status: Literal["verified", "needs_review"]


class PolicyClauseResponse(BaseModel):
    """Policy clause with original document and page provenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    source_chunk_id: UUID
    clause_identifier: str
    clause_category: str
    title: str | None
    clause_text: str
    source_page_number: int
    verification_status: str
    verified_by_employee_id: UUID | None
    verified_at: datetime | None


class PolicyDocumentApplicability(BaseModel):
    """Verified applicability metadata supplied by policy administrators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supported_claim_types: list[str] = Field(min_length=1, max_length=20)
    policy_identifier: str = Field(min_length=1, max_length=150)
    insurer_name: str | None = Field(default=None, max_length=150)
    product_name: str | None = Field(default=None, max_length=200)
    insurance_type: str | None = None
    policy_version: str | None = Field(default=None, max_length=100)
    effective_from: date | None = None
    effective_to: date | None = None
    storage_status: str | None = None

    @field_validator("supported_claim_types")
    @classmethod
    def normalize_claim_types(cls, values: list[str]) -> list[str]:
        normalized = [normalize_insurance_type(value) for value in values]
        supported_types = {"auto", "property", "health"}
        if any(not value or len(value) > 100 for value in normalized):
            raise ValueError(
                "Supported claim types must be non-empty and at most "
                "100 characters."
            )
        if set(normalized) - supported_types:
            raise ValueError("Unsupported insurance claim type.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Supported claim types must be unique.")
        return normalized

    @field_validator("insurance_type", mode="before")
    @classmethod
    def normalize_insurance_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Unsupported insurance type.")
        normalized = normalize_insurance_type(value)
        if normalized not in {"auto", "property", "health"}:
            raise ValueError("Unsupported insurance type.")
        return normalized

    @field_validator("policy_version")
    @classmethod
    def normalize_policy_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Policy version must not be blank.")
        return normalized

    @field_validator("policy_identifier")
    @classmethod
    def normalize_policy_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Policy identifier must not be blank.")
        return normalized

    @field_validator("insurer_name", "product_name")
    @classmethod
    def normalize_optional_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Policy metadata must not be blank.")
        return normalized

    @model_validator(mode="after")
    def validate_version_metadata(self) -> "PolicyDocumentApplicability":
        supplied = (
            self.insurance_type is not None,
            self.policy_version is not None,
            self.effective_from is not None,
        )
        if (any(supplied) or self.effective_to is not None) and not all(
            supplied
        ):
            raise ValueError(
                "insurance_type, policy_version, and effective_from "
                "must be provided together."
            )
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to cannot be before effective_from.")
        if (
            self.insurance_type is not None
            and self.insurance_type not in self.supported_claim_types
        ):
            raise ValueError(
                "insurance_type must be one of the supported claim types."
            )
        return self


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
