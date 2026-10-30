
"""Policy document API response schemas."""

from uuid import UUID

from pydantic import BaseModel


class PolicyDocumentUploadResponse(BaseModel):
    """Response returned after a policy document upload."""

    document_id: UUID
    filename: str
    status: str
    chunk_count: int
