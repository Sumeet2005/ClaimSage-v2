"""Add strict policy applicability metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c4a2d8e17b1"
down_revision: str | Sequence[str] | None = "fba60779f809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable policy identifiers and explicit claim-type applicability."""

    op.add_column(
        "claims",
        sa.Column("policy_identifier", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "policy_documents",
        sa.Column("policy_identifier", sa.String(length=150), nullable=True),
    )
    op.create_index(
        "ix_policy_documents_policy_identifier",
        "policy_documents",
        ["policy_identifier"],
    )
    op.create_table(
        "policy_document_applicability",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("claim_type", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["policy_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "claim_type",
            name="uq_policy_document_applicability_document_claim_type",
        ),
    )
    op.create_index(
        "ix_policy_document_applicability_claim_type",
        "policy_document_applicability",
        ["claim_type"],
    )


def downgrade() -> None:
    """Remove policy applicability metadata."""

    op.drop_index(
        "ix_policy_document_applicability_claim_type",
        table_name="policy_document_applicability",
    )
    op.drop_table("policy_document_applicability")
    op.drop_index(
        "ix_policy_documents_policy_identifier",
        table_name="policy_documents",
    )
    op.drop_column("policy_documents", "policy_identifier")
    op.drop_column("claims", "policy_identifier")
