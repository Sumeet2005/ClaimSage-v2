"""ClaimSage database models."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from claimsage.db.base import Base


class EmployeeRole(StrEnum):
    """Roles used by ClaimSage authorization policies."""

    CLAIMS_ADJUSTER = "claims_adjuster"
    TEAM_LEAD = "team_lead"
    POLICY_SPECIALIST = "policy_specialist"
    ADMIN = "admin"

    # Phase 9 two-role architecture alias
    CLAIMS_ANALYST = "claims_adjuster"


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
    policy_identifier: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    insurer_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    product_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    loss_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    team_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    assigned_employee: Mapped[Employee | None] = relationship()


class AuditEvent(Base):
    """Enterprise append-only record of important application, agent, and system actions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_claim_created", "claim_id", "created_at"),
        Index("ix_audit_events_investigation_created", "investigation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_type: Mapped[str] = mapped_column(
        String(30),
        default="employee",
        server_default="employee",
        nullable=False,
        index=True,
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    actor_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id"),
        nullable=True,
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "claims.id",
            name="fk_audit_events_claim_id_claims",
            ondelete="CASCADE",
        ),
        nullable=True,
        index=True,
    )
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_runs.id",
            name="fk_audit_events_investigation_id_runs",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    event_category: Mapped[str] = mapped_column(
        String(50),
        default="claim",
        server_default="claim",
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), index=True)
    outcome: Mapped[str] = mapped_column(
        String(20),
        default="success",
        server_default="success",
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )

    actor_employee: Mapped[Employee | None] = relationship()

    @property
    def actor_name(self) -> str:
        if self.actor_employee:
            return self.actor_employee.display_name
        if self.actor_id:
            return self.actor_id
        return self.actor_type.title()


class NotificationDelivery(Base):
    """Idempotent email outbox record without message or claim contents."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(
            "event_type IN "
            "('claim_received', 'investigation_completed', "
            "'human_review_required', 'additional_evidence_required', "
            "'review_completed')",
            name="ck_notification_deliveries_event_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'delivered', 'sandboxed', 'failed')",
            name="ck_notification_deliveries_status_valid",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_notification_deliveries_idempotency_key",
        ),
        Index("ix_notification_deliveries_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            name="fk_notification_deliveries_employee_id_employees",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    resource_id: Mapped[str] = mapped_column(String(100), nullable=False)
    application_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        nullable=False,
    )
    last_error_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
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
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    recipient: Mapped[Employee] = relationship()


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
        Index(
            "ix_policy_documents_policy_identifier",
            "policy_identifier",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL "
            "OR effective_to >= effective_from",
            name="ck_policy_documents_effective_date_order",
        ),
        CheckConstraint(
            "insurance_type IS NULL OR "
            "insurance_type IN ('auto', 'property', 'health')",
            name="ck_policy_documents_insurance_type_valid",
        ),
        Index("ix_policy_documents_storage_key", "storage_key"),
        CheckConstraint(
            "storage_status IS NULL OR "
            "storage_status IN ('stored', 'pending', 'failed', 'unavailable')",
            name="ck_policy_documents_storage_status_valid",
        ),
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
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    insurer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    policy_identifier: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )
    insurance_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )
    policy_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    uploaded_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    storage_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default="s3",
        server_default="s3",
    )
    storage_bucket: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    storage_key: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    storage_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default="unavailable",
        server_default="unavailable",
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
    supported_claim_types: Mapped[list["PolicyDocumentApplicability"]] = (
        relationship(
            back_populates="document",
            cascade="all, delete-orphan",
            passive_deletes=True,
        )
    )
    clauses: Mapped[list["PolicyClause"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    coverages: Mapped[list["PolicyCoverage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    exclusions: Mapped[list["PolicyExclusion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PolicyDocumentApplicability(Base):
    """Claim types explicitly declared applicable to a policy document."""

    __tablename__ = "policy_document_applicability"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "claim_type",
            name="uq_policy_document_applicability_document_claim_type",
        ),
        Index(
            "ix_policy_document_applicability_claim_type",
            "claim_type",
        ),
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
    claim_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    document: Mapped[PolicyDocument] = relationship(
        back_populates="supported_claim_types",
    )


class PolicyClause(Base):
    """Source-traceable clause text awaiting explicit human verification."""

    __tablename__ = "policy_clauses"
    __table_args__ = (
        UniqueConstraint(
            "source_chunk_id",
            name="uq_policy_clauses_source_chunk",
        ),
        CheckConstraint(
            "clause_category IN "
            "('coverage', 'exclusion', 'condition', 'deductible', 'limit', "
            "'definition', 'endorsement', 'evidence_requirement', 'other')",
            name="ck_policy_clauses_category_valid",
        ),
        CheckConstraint(
            "verification_status IN "
            "('pending_review', 'verified', 'needs_review')",
            name="ck_policy_clauses_verification_status_valid",
        ),
        CheckConstraint(
            "source_page_number > 0",
            name="ck_policy_clauses_source_page_positive",
        ),
        Index("ix_policy_clauses_document_id", "document_id"),
        Index(
            "ix_policy_clauses_document_identifier",
            "document_id",
            "clause_identifier",
        ),
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
    source_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("policy_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    clause_identifier: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    clause_category: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="other",
        server_default="other",
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clause_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_page_number: Mapped[int] = mapped_column(nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_review",
        server_default="pending_review",
    )
    verified_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    document: Mapped[PolicyDocument] = relationship(back_populates="clauses")
    source_chunk: Mapped["PolicyChunk"] = relationship()


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


class PolicyCoverage(Base):
    """Structured coverage category, benefit limit, deductible, and co-pay term."""

    __tablename__ = "policy_coverages"
    __table_args__ = (
        CheckConstraint(
            "benefit_limit IS NULL OR benefit_limit >= 0",
            name="ck_policy_coverages_benefit_limit_nonnegative",
        ),
        CheckConstraint(
            "deductible IS NULL OR deductible >= 0",
            name="ck_policy_coverages_deductible_nonnegative",
        ),
        CheckConstraint(
            "co_pay_percentage IS NULL OR (co_pay_percentage >= 0 AND co_pay_percentage <= 100)",
            name="ck_policy_coverages_co_pay_percentage_range",
        ),
        CheckConstraint(
            "waiting_period_days IS NULL OR waiting_period_days >= 0",
            name="ck_policy_coverages_waiting_period_nonnegative",
        ),
        CheckConstraint(
            "length(trim(coverage_name)) > 0",
            name="ck_policy_coverages_name_nonempty",
        ),
        Index("ix_policy_coverages_document_id", "document_id"),
        Index("ix_policy_coverages_category", "coverage_category"),
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
    coverage_name: Mapped[str] = mapped_column(String(150), nullable=False)
    coverage_category: Mapped[str] = mapped_column(
        String(50),
        default="inpatient",
        server_default="inpatient",
        nullable=False,
    )
    benefit_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )
    deductible: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2),
        nullable=True,
    )
    co_pay_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
    )
    waiting_period_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_optional: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[PolicyDocument] = relationship(back_populates="coverages")


class PolicyExclusion(Base):
    """Explicitly excluded condition, treatment, waiting period, or peril."""

    __tablename__ = "policy_exclusions"
    __table_args__ = (
        CheckConstraint(
            "waiting_period_months IS NULL OR waiting_period_months >= 0",
            name="ck_policy_exclusions_waiting_period_nonnegative",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_policy_exclusions_title_nonempty",
        ),
        CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_policy_exclusions_description_nonempty",
        ),
        CheckConstraint(
            "exclusion_type IN ('permanent', 'waiting_period', 'condition_based', 'specified_illness', 'other')",
            name="ck_policy_exclusions_type_valid",
        ),
        Index("ix_policy_exclusions_document_id", "document_id"),
        Index("ix_policy_exclusions_code", "exclusion_code"),
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
    exclusion_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    waiting_period_months: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    exclusion_type: Mapped[str] = mapped_column(
        String(50),
        default="permanent",
        server_default="permanent",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document: Mapped[PolicyDocument] = relationship(back_populates="exclusions")


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
        Index(
            "ix_claim_evidence_documents_storage_key",
            "storage_key",
        ),
        CheckConstraint(
            "storage_status IS NULL OR "
            "storage_status IN ('stored', 'pending', 'failed', 'unavailable')",
            name="ck_claim_evidence_documents_storage_status_valid",
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

    storage_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default="s3",
        server_default="s3",
    )
    storage_bucket: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    storage_key: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    storage_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default="unavailable",
        server_default="unavailable",
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


class InvestigationRun(Base):
    """Durable execution record for one claim investigation."""

    __tablename__ = "investigation_runs"
    __table_args__ = (
        CheckConstraint(
            "claim_domain IN ('auto', 'health', 'other')",
            name="ck_investigation_runs_domain_valid",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'incomplete', 'failed')",
            name="ck_investigation_runs_status_valid",
        ),
        CheckConstraint(
            "human_review_status IN "
            "('pending', 'reviewed', 'needs_follow_up', 'escalated', 'approved', 'needs_additional_documents', 'returned_for_investigation')",
            name="ck_investigation_runs_review_status_valid",
        ),
        Index(
            "ix_investigation_runs_claim_created_at",
            "claim_id",
            "created_at",
        ),
        Index("ix_investigation_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "claims.id",
            name="fk_investigation_runs_claim_id_claims",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    claim_domain: Mapped[str] = mapped_column(String(20), nullable=False)
    initiated_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            name="fk_investigation_runs_initiated_by_employee_id_employees",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="running",
        server_default="running",
        nullable=False,
    )
    current_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    human_review_status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    state_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    failure_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        default=3,
        server_default="3",
        nullable=False,
    )
    repair_estimate_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    claim: Mapped[Claim] = relationship()
    initiated_by: Mapped[Employee] = relationship()
    findings: Mapped[list["InvestigationFinding"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    report: Mapped["InvestigationReport | None"] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    reviews: Mapped[list["InvestigationReview"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvestigationReview.created_at",
    )


class InvestigationFinding(Base):
    """One source-preserving finding or limitation from a specialist output."""

    __tablename__ = "investigation_findings"
    __table_args__ = (
        Index(
            "ix_investigation_findings_run_specialist",
            "investigation_id",
            "specialist",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_runs.id",
            name="fk_investigation_findings_investigation_id_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    specialist: Mapped[str] = mapped_column(String(50), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(100), nullable=False)
    finding_data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidence_references: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    policy_references: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    investigation: Mapped[InvestigationRun] = relationship(
        back_populates="findings",
    )
    source_references: Mapped[list["InvestigationFindingReference"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    edits: Mapped[list["InvestigationFindingEdit"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvestigationFindingEdit.created_at.desc()",
    )


class InvestigationFindingReference(Base):
    """Relational link and captured provenance for a finding source."""

    __tablename__ = "investigation_finding_references"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('claim_evidence', 'policy_chunk', 'policy_clause', "
            "'analyst_output', 'unresolved')",
            name="ck_investigation_finding_references_kind_valid",
        ),
        CheckConstraint(
            "num_nonnulls(claim_evidence_chunk_id, policy_chunk_id, "
            "policy_clause_id) <= 1",
            name="ck_investigation_finding_references_single_source",
        ),
        Index(
            "ix_investigation_finding_references_finding_id",
            "finding_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_findings.id",
            name="fk_investigation_finding_references_finding_id_findings",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    claim_evidence_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "claim_evidence_chunks.id",
            name="fk_investigation_finding_references_claim_chunk",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    policy_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "policy_chunks.id",
            name="fk_investigation_finding_references_policy_chunk",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    policy_clause_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "policy_clauses.id",
            name="fk_investigation_finding_references_policy_clause",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    finding: Mapped[InvestigationFinding] = relationship(
        back_populates="source_references",
    )
    claim_evidence_chunk: Mapped[ClaimEvidenceChunk | None] = relationship()
    policy_chunk: Mapped[PolicyChunk | None] = relationship()
    policy_clause: Mapped[PolicyClause | None] = relationship()


class InvestigationReport(Base):
    """Persisted report output and report-generation status."""

    __tablename__ = "investigation_reports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'incomplete', 'unavailable', 'skipped')",
            name="ck_investigation_reports_status_valid",
        ),
        UniqueConstraint(
            "investigation_id",
            name="uq_investigation_reports_investigation_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_runs.id",
            name="fk_investigation_reports_investigation_id_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    report_data: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    human_review_required: Mapped[bool] = mapped_column(
        default=True,
        server_default="true",
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

    investigation: Mapped[InvestigationRun] = relationship(
        back_populates="report",
    )


class InvestigationReview(Base):
    """Append-only human review decision without claim disposition authority."""

    __tablename__ = "investigation_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('reviewed', 'needs_follow_up', 'escalated', 'approved', 'needs_additional_documents', 'returned_for_investigation')",
            name="ck_investigation_reviews_decision_valid",
        ),
        Index(
            "ix_investigation_reviews_run_created_at",
            "investigation_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_runs.id",
            name="fk_investigation_reviews_investigation_id_runs",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    reviewer_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            name="fk_investigation_reviews_reviewer_employee_id_employees",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    investigation: Mapped[InvestigationRun] = relationship(
        back_populates="reviews",
    )
    reviewer: Mapped[Employee] = relationship()


class InvestigationFindingEdit(Base):
    """Human modification to an AI-generated finding, preserving the original data."""

    __tablename__ = "investigation_finding_edits"
    __table_args__ = (
        Index(
            "ix_finding_edits_finding_id",
            "finding_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_findings.id",
            name="fk_finding_edits_finding_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_runs.id",
            name="fk_finding_edits_investigation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    editor_employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            name="fk_finding_edits_editor_employee_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    original_data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    edited_data: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    finding: Mapped["InvestigationFinding"] = relationship(
        back_populates="edits",
    )
    editor: Mapped[Employee] = relationship()

    @property
    def editor_name(self) -> str:
        return self.editor.display_name if self.editor else "Unknown"


class CustomerEmail(Base):
    """Customer-facing email communication requiring explicit human approval."""

    __tablename__ = "customer_emails"
    __table_args__ = (
        CheckConstraint(
            "status IN ('drafted', 'approved', 'queued', 'sent', 'bounced', 'replied', 'failed')",
            name="ck_customer_emails_status_valid",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_customer_emails_idempotency_key",
        ),
        Index("ix_customer_emails_claim_status", "claim_id", "status"),
        Index("ix_customer_emails_deadline", "status", "follow_up_deadline"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "claims.id",
            name="fk_customer_emails_claim_id_claims",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "investigation_runs.id",
            name="fk_customer_emails_investigation_id_runs",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default="drafted",
        server_default="drafted",
        nullable=False,
    )
    approved_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "employees.id",
            name="fk_customer_emails_approved_by_employee_id_employees",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    secure_upload_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    secure_upload_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    follow_up_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        default=3,
        server_default="3",
        nullable=False,
    )
    last_error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    investigation: Mapped[InvestigationRun | None] = relationship()
    approved_by: Mapped[Employee | None] = relationship()

    @property
    def approved_by_name(self) -> str | None:
        return self.approved_by.display_name if self.approved_by else None
