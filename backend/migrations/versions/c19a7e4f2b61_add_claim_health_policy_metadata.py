"""Add insurer and product metadata to claims."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c19a7e4f2b61"
down_revision: str | Sequence[str] | None = "4a8f3c2d1e90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable claim-side policy metadata for applicability matching."""

    op.add_column(
        "claims",
        sa.Column("insurer_name", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "claims",
        sa.Column("product_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Remove claim-side policy metadata."""

    op.drop_column("claims", "product_name")
    op.drop_column("claims", "insurer_name")
