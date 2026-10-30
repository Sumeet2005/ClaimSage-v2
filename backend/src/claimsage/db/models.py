"""ClaimSage database models."""

import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from claimsage.db.base import Base


class EmployeeRole(StrEnum):
    """Roles used by ClaimSage authorization policies."""

    CLAIMS_ADJUSTER = "claims_adjuster"
    TEAM_LEAD = "team_lead"
    POLICY_SPECIALIST = "policy_specialist"
    ADMIN = "admin"


class Employee(Base):
    """Internal employee account."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))

    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    role: Mapped[EmployeeRole] = mapped_column(
        Enum(EmployeeRole, name="employee_role"),
        default=EmployeeRole.CLAIMS_ADJUSTER,
        nullable=False,
    )
    team_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Claim(Base):
    """Synthetic insurance claim record."""

    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    claim_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
    )
    claimant_name: Mapped[str] = mapped_column(String(200))
    claim_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(50),
        default="under_review",
        nullable=False,
    )
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=True,
    )
    team_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    assigned_employee: Mapped[Employee | None] = relationship()


class AuditEvent(Base):
    """Record of important application actions."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )


class PolicyDocument(Base):
    """Uploaded policy document and its ingestion metadata."""

    __tablename__ = "policy_documents"
    __table_args__ = (
        CheckConstraint(
            "file_size_bytes > 0",
            name="ck_policy_documents_file_size_positive",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'failed')",
            name="ck_policy_documents_status_valid",
        ),
        Index("ix_policy_documents_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(nullable=False)
    uploaded_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="uploaded",
        server_default="uploaded",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    uploaded_by: Mapped[Employee] = relationship()
    chunks: Mapped[list["PolicyChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PolicyChunk(Base):
    """Text chunk extracted from a policy document."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="uq_policy_chunks_document_page_index",
        ),
        CheckConstraint(
            "page_number > 0",
            name="ck_policy_chunks_page_number_positive",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_policy_chunks_index_nonnegative",
        ),
        CheckConstraint(
            "length(text) > 0",
            name="ck_policy_chunks_text_nonempty",
        ),
        CheckConstraint(
            "extraction_method IN ('native', 'ocr')",
            name="ck_policy_chunks_extraction_method_valid",
        ),
        CheckConstraint(
            "ocr_confidence IS NULL OR "
            "(ocr_confidence >= 0 AND ocr_confidence <= 100)",
            name="ck_policy_chunks_ocr_confidence_valid",
        ),
        Index("ix_policy_chunks_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policy_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # Extraction provenance.
    extraction_method: Mapped[str] = mapped_column(
        String(20),
        default="native",
        server_default="native",
        nullable=False,
    )
    ocr_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Nullable so existing chunks remain valid until embeddings are generated.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[PolicyDocument] = relationship(
        back_populates="chunks",
    )


class PolicyDocumentAccess(Base):
    """Explicit team-level or claim-level access to a policy document."""

    __tablename__ = "policy_document_access"

    __table_args__ = (
        CheckConstraint(
            """
            (
                team_id IS NOT NULL
                AND claim_id IS NULL
                AND length(trim(team_id)) > 0
            )
            OR
            (
                team_id IS NULL
                AND claim_id IS NOT NULL
            )
            """,
            name="ck_policy_document_access_exactly_one_scope",
        ),
        UniqueConstraint(
            "document_id",
            "team_id",
            name="uq_policy_document_access_document_team",
        ),
        UniqueConstraint(
            "document_id",
            "claim_id",
            name="uq_policy_document_access_document_claim",
        ),
        Index("ix_policy_document_access_document_id", "document_id"),
        Index("ix_policy_document_access_team_id", "team_id"),
        Index("ix_policy_document_access_claim_id", "claim_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policy_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    team_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=True,
    )

    granted_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

class ClaimEvidenceDocument(Base):
    """Evidence document uploaded for a specific insurance claim."""

    __tablename__ = "claim_evidence_documents"

    __table_args__ = (
        UniqueConstraint(
            "claim_id",
            "checksum_sha256",
            name="uq_claim_evidence_document_claim_checksum",
        ),
        CheckConstraint(
            "file_size_bytes > 0",
            name="ck_claim_evidence_documents_file_size_positive",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'failed')",
            name="ck_claim_evidence_documents_status_valid",
        ),
        Index(
            "ix_claim_evidence_documents_claim_id",
            "claim_id",
        ),
        Index(
            "ix_claim_evidence_documents_created_at",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    checksum_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    file_size_bytes: Mapped[int] = mapped_column(
        nullable=False,
    )

    uploaded_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="uploaded",
        server_default="uploaded",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    claim: Mapped[Claim] = relationship()
    uploaded_by: Mapped[Employee] = relationship()

    chunks: Mapped[list["ClaimEvidenceChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClaimEvidenceChunk(Base):
    """Page-aware extracted text and embedding for claim evidence."""

    __tablename__ = "claim_evidence_chunks"

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="uq_claim_evidence_chunks_document_page_index",
        ),
        CheckConstraint(
            "page_number > 0",
            name="ck_claim_evidence_chunks_page_number_positive",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_claim_evidence_chunks_index_nonnegative",
        ),
        CheckConstraint(
            "length(text) > 0",
            name="ck_claim_evidence_chunks_text_nonempty",
        ),
        CheckConstraint(
            "extraction_method IN ('native', 'ocr')",
            name="ck_claim_evidence_chunks_extraction_method_valid",
        ),
        CheckConstraint(
            "ocr_confidence IS NULL OR "
            "(ocr_confidence >= 0 AND ocr_confidence <= 100)",
            name="ck_claim_evidence_chunks_ocr_confidence_valid",
        ),
        Index(
            "ix_claim_evidence_chunks_document_id",
            "document_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claim_evidence_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    page_number: Mapped[int] = mapped_column(nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)

    chunk_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    extraction_method: Mapped[str] = mapped_column(
        String(20),
        default="native",
        server_default="native",
        nullable=False,
    )

    ocr_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )

    embedding_model: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[ClaimEvidenceDocument] = relationship(
        back_populates="chunks",
    )
