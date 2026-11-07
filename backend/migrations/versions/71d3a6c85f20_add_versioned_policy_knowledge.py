"""Add versioned policy metadata and source-traceable clauses."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "71d3a6c85f20"
down_revision: str | Sequence[str] | None = "9c4a2d8e17b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable policy version metadata without classifying old records."""

    op.add_column(
        "claims",
        sa.Column("loss_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "policy_documents",
        sa.Column("insurance_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "policy_documents",
        sa.Column("policy_version", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "policy_documents",
        sa.Column("effective_from", sa.Date(), nullable=True),
    )
    op.add_column(
        "policy_documents",
        sa.Column("effective_to", sa.Date(), nullable=True),
    )
    op.create_check_constraint(
        "ck_policy_documents_effective_date_order",
        "policy_documents",
        "effective_to IS NULL OR effective_from IS NULL "
        "OR effective_to >= effective_from",
    )
    op.create_check_constraint(
        "ck_policy_documents_insurance_type_valid",
        "policy_documents",
        "insurance_type IS NULL OR "
        "insurance_type IN ('auto', 'property', 'health')",
    )
    op.create_index(
        "ix_policy_documents_policy_version",
        "policy_documents",
        ["policy_identifier", "policy_version"],
    )
    op.create_table(
        "policy_clauses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("source_chunk_id", sa.UUID(), nullable=False),
        sa.Column("clause_identifier", sa.String(length=150), nullable=False),
        sa.Column(
            "clause_category",
            sa.String(length=30),
            server_default="other",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("clause_text", sa.Text(), nullable=False),
        sa.Column("source_page_number", sa.Integer(), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=30),
            server_default="pending_review",
            nullable=False,
        ),
        sa.Column("verified_by_employee_id", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "clause_category IN "
            "('coverage', 'exclusion', 'condition', 'deductible', 'limit', "
            "'definition', 'endorsement', 'evidence_requirement', 'other')",
            name="ck_policy_clauses_category_valid",
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('pending_review', 'verified', 'needs_review')",
            name="ck_policy_clauses_verification_status_valid",
        ),
        sa.CheckConstraint(
            "source_page_number > 0",
            name="ck_policy_clauses_source_page_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["policy_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk_id"],
            ["policy_chunks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_chunk_id",
            name="uq_policy_clauses_source_chunk",
        ),
    )
    op.create_index(
        "ix_policy_clauses_document_id",
        "policy_clauses",
        ["document_id"],
    )
    op.create_index(
        "ix_policy_clauses_document_identifier",
        "policy_clauses",
        ["document_id", "clause_identifier"],
    )


def downgrade() -> None:
    """Remove policy clause records and nullable version metadata."""

    op.drop_index(
        "ix_policy_clauses_document_identifier",
        table_name="policy_clauses",
    )
    op.drop_index("ix_policy_clauses_document_id", table_name="policy_clauses")
    op.drop_table("policy_clauses")
    op.drop_index(
        "ix_policy_documents_policy_version",
        table_name="policy_documents",
    )
    op.drop_constraint(
        "ck_policy_documents_insurance_type_valid",
        "policy_documents",
        type_="check",
    )
    op.drop_constraint(
        "ck_policy_documents_effective_date_order",
        "policy_documents",
        type_="check",
    )
    op.drop_column("policy_documents", "effective_to")
    op.drop_column("policy_documents", "effective_from")
    op.drop_column("policy_documents", "policy_version")
    op.drop_column("policy_documents", "insurance_type")
    op.drop_column("claims", "loss_date")
