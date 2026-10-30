
"""Add local embedding storage to policy chunks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# Revision identifiers.
revision: str = "e71754403b12"
down_revision: str | Sequence[str] | None = "b4b450be3415"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable embedding metadata to existing policy chunks."""

    op.add_column(
        "policy_chunks",
        sa.Column(
            "embedding",
            Vector(384),
            nullable=True,
        ),
    )

    op.add_column(
        "policy_chunks",
        sa.Column(
            "embedding_model",
            sa.String(length=150),
            nullable=True,
        ),
    )

    op.add_column(
        "policy_chunks",
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove embedding columns from policy chunks."""

    op.drop_column("policy_chunks", "embedded_at")
    op.drop_column("policy_chunks", "embedding_model")
    op.drop_column("policy_chunks", "embedding")
