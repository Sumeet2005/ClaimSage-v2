"""Claim evidence API request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ClaimEvidenceUploadResponse(BaseModel):
    """Response returned after claim evidence is uploaded and processed."""

    document_id: UUID
    claim_id: UUID
    filename: str
    status: str
    chunk_count: int
    storage_status: str | None = None


class ClaimEvidenceItemResponse(BaseModel):
    """Item representation for listing evidence documents across claims."""

    id: UUID
    claim_id: UUID
    claim_number: str
    claimant_name: str
    filename: str
    file_size_bytes: int
    mime_type: str
    storage_status: str
    status: str
    chunk_count: int
    uploaded_at: datetime
    uploaded_by_name: str | None = None
