"""Persist original source URLs for policy documents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d9f3420a17"
down_revision: str | Sequence[str] | None = "a8f4c2d9e761"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store the public URL from which a policy document was obtained."""
    op.add_column(
        "policy_documents",
        sa.Column("source_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove policy source URL provenance."""
    op.drop_column("policy_documents", "source_url")
