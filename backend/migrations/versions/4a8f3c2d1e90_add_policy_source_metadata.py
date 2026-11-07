"""Preserve insurer and product metadata on policy documents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a8f3c2d1e90"
down_revision: str | Sequence[str] | None = "c6d9f3420a17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add descriptive policy source metadata without changing existing rows."""
    op.add_column(
        "policy_documents",
        sa.Column("insurer_name", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "policy_documents",
        sa.Column("product_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Remove descriptive policy source metadata."""
    op.drop_column("policy_documents", "product_name")
    op.drop_column("policy_documents", "insurer_name")
