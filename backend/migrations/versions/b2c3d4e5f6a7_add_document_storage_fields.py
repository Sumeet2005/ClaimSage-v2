"""Add durable object storage fields to policy and evidence documents.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-04 02:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add storage fields to policy_documents
    op.add_column(
        "policy_documents",
        sa.Column(
            "storage_provider",
            sa.String(length=50),
            server_default="s3",
            nullable=True,
        ),
    )
    op.add_column(
        "policy_documents",
        sa.Column(
            "storage_bucket",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "policy_documents",
        sa.Column(
            "storage_key",
            sa.String(length=500),
            nullable=True,
        ),
    )
    op.add_column(
        "policy_documents",
        sa.Column(
            "storage_status",
            sa.String(length=30),
            server_default="unavailable",
            nullable=True,
        ),
    )
    op.create_index(
        "ix_policy_documents_storage_key",
        "policy_documents",
        ["storage_key"],
    )
    op.create_check_constraint(
        "ck_policy_documents_storage_status_valid",
        "policy_documents",
        "storage_status IS NULL OR storage_status IN ('stored', 'pending', 'failed', 'unavailable')",
    )

    # 2. Add storage fields to claim_evidence_documents
    op.add_column(
        "claim_evidence_documents",
        sa.Column(
            "storage_provider",
            sa.String(length=50),
            server_default="s3",
            nullable=True,
        ),
    )
    op.add_column(
        "claim_evidence_documents",
        sa.Column(
            "storage_bucket",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        "claim_evidence_documents",
        sa.Column(
            "storage_key",
            sa.String(length=500),
            nullable=True,
        ),
    )
    op.add_column(
        "claim_evidence_documents",
        sa.Column(
            "storage_status",
            sa.String(length=30),
            server_default="unavailable",
            nullable=True,
        ),
    )
    op.create_index(
        "ix_claim_evidence_documents_storage_key",
        "claim_evidence_documents",
        ["storage_key"],
    )
    op.create_check_constraint(
        "ck_claim_evidence_documents_storage_status_valid",
        "claim_evidence_documents",
        "storage_status IS NULL OR storage_status IN ('stored', 'pending', 'failed', 'unavailable')",
    )


def downgrade() -> None:
    # 1. Revert claim_evidence_documents
    op.drop_constraint(
        "ck_claim_evidence_documents_storage_status_valid",
        "claim_evidence_documents",
        type_="check",
    )
    op.drop_index(
        "ix_claim_evidence_documents_storage_key",
        table_name="claim_evidence_documents",
    )
    op.drop_column("claim_evidence_documents", "storage_status")
    op.drop_column("claim_evidence_documents", "storage_key")
    op.drop_column("claim_evidence_documents", "storage_bucket")
    op.drop_column("claim_evidence_documents", "storage_provider")

    # 2. Revert policy_documents
    op.drop_constraint(
        "ck_policy_documents_storage_status_valid",
        "policy_documents",
        type_="check",
    )
    op.drop_index(
        "ix_policy_documents_storage_key",
        table_name="policy_documents",
    )
    op.drop_column("policy_documents", "storage_status")
    op.drop_column("policy_documents", "storage_key")
    op.drop_column("policy_documents", "storage_bucket")
    op.drop_column("policy_documents", "storage_provider")
