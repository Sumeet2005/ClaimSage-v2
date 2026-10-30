"""Add extraction provenance to policy chunks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d92a6f31c840"
down_revision: str | Sequence[str] | None = "c45fe0c67286"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add extraction method and OCR confidence metadata."""

    op.add_column(
        "policy_chunks",
        sa.Column(
            "extraction_method",
            sa.String(length=20),
            server_default="native",
            nullable=False,
        ),
    )

    op.add_column(
        "policy_chunks",
        sa.Column(
            "ocr_confidence",
            sa.Float(),
            nullable=True,
        ),
    )

    op.create_check_constraint(
        "ck_policy_chunks_extraction_method_valid",
        "policy_chunks",
        "extraction_method IN ('native', 'ocr')",
    )

    op.create_check_constraint(
        "ck_policy_chunks_ocr_confidence_valid",
        "policy_chunks",
        "ocr_confidence IS NULL OR "
        "(ocr_confidence >= 0 AND ocr_confidence <= 100)",
    )


def downgrade() -> None:
    """Remove extraction provenance metadata."""

    op.drop_constraint(
        "ck_policy_chunks_ocr_confidence_valid",
        "policy_chunks",
        type_="check",
    )

    op.drop_constraint(
        "ck_policy_chunks_extraction_method_valid",
        "policy_chunks",
        type_="check",
    )

    op.drop_column("policy_chunks", "ocr_confidence")
    op.drop_column("policy_chunks", "extraction_method")
