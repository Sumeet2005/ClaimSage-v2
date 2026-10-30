"""Add explicit team-level and claim-level policy document access grants."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c45fe0c67286"
down_revision: str | Sequence[str] | None = "e71754403b12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create explicit policy document access grants."""

    op.create_table(
        "policy_document_access",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", sa.String(length=100), nullable=True),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "granted_by_employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["policy_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "team_id",
            name="uq_policy_document_access_document_team",
        ),
        sa.UniqueConstraint(
            "document_id",
            "claim_id",
            name="uq_policy_document_access_document_claim",
        ),
    )

    op.create_index(
        "ix_policy_document_access_document_id",
        "policy_document_access",
        ["document_id"],
    )
    op.create_index(
        "ix_policy_document_access_team_id",
        "policy_document_access",
        ["team_id"],
    )
    op.create_index(
        "ix_policy_document_access_claim_id",
        "policy_document_access",
        ["claim_id"],
    )


def downgrade() -> None:
    """Remove policy document access grants."""

    op.drop_index(
        "ix_policy_document_access_claim_id",
        table_name="policy_document_access",
    )
    op.drop_index(
        "ix_policy_document_access_team_id",
        table_name="policy_document_access",
    )
    op.drop_index(
        "ix_policy_document_access_document_id",
        table_name="policy_document_access",
    )
    op.drop_table("policy_document_access")
