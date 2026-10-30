"""Add claim evidence document and chunk persistence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "fba60779f809"
down_revision: str | Sequence[str] | None = "d92a6f31c840"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create claim evidence document and chunk tables."""

    op.create_table(
        "claim_evidence_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_employee_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="uploaded",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'processed', 'failed')",
            name="ck_claim_evidence_documents_status_valid",
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0",
            name="ck_claim_evidence_documents_file_size_positive",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "checksum_sha256",
            name="uq_claim_evidence_document_claim_checksum",
        ),
    )

    op.create_index(
        "ix_claim_evidence_documents_claim_id",
        "claim_evidence_documents",
        ["claim_id"],
    )
    op.create_index(
        "ix_claim_evidence_documents_created_at",
        "claim_evidence_documents",
        ["created_at"],
    )

    op.create_table(
        "claim_evidence_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "extraction_method",
            sa.String(length=20),
            server_default="native",
            nullable=False,
        ),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("embedding_model", sa.String(length=150), nullable=True),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "extraction_method IN ('native', 'ocr')",
            name="ck_claim_evidence_chunks_extraction_method_valid",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_claim_evidence_chunks_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(text) > 0",
            name="ck_claim_evidence_chunks_text_nonempty",
        ),
        sa.CheckConstraint(
            "ocr_confidence IS NULL OR "
            "(ocr_confidence >= 0 AND ocr_confidence <= 100)",
            name="ck_claim_evidence_chunks_ocr_confidence_valid",
        ),
        sa.CheckConstraint(
            "page_number > 0",
            name="ck_claim_evidence_chunks_page_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["claim_evidence_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="uq_claim_evidence_chunks_document_page_index",
        ),
    )

    op.create_index(
        "ix_claim_evidence_chunks_document_id",
        "claim_evidence_chunks",
        ["document_id"],
    )


def downgrade() -> None:
    """Remove claim evidence tables."""

    op.drop_index(
        "ix_claim_evidence_chunks_document_id",
        table_name="claim_evidence_chunks",
    )
    op.drop_table("claim_evidence_chunks")

    op.drop_index(
        "ix_claim_evidence_documents_created_at",
        table_name="claim_evidence_documents",
    )
    op.drop_index(
        "ix_claim_evidence_documents_claim_id",
        table_name="claim_evidence_documents",
    )
    op.drop_table("claim_evidence_documents")
