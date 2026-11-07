"""Add investigation queue lease and retry columns to investigation_runs.

Revision ID: e2b4f6a8c0d1
Revises: d0c17a2f9b64
Create Date: 2026-11-03 21:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e2b4f6a8c0d1"
down_revision: str | Sequence[str] | None = "d0c17a2f9b64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add worker leasing, heartbeat, and retry columns to investigation_runs."""
    op.add_column(
        "investigation_runs",
        sa.Column("worker_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "investigation_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "investigation_runs",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "investigation_runs",
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.add_column(
        "investigation_runs",
        sa.Column(
            "repair_estimate_document_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_investigation_runs_queue_claim",
        "investigation_runs",
        ["status", "current_stage", "lease_expires_at"],
    )


def downgrade() -> None:
    """Remove worker leasing and retry columns."""
    op.drop_index("ix_investigation_runs_queue_claim", table_name="investigation_runs")
    op.drop_column("investigation_runs", "repair_estimate_document_id")
    op.drop_column("investigation_runs", "max_attempts")
    op.drop_column("investigation_runs", "attempt_count")
    op.drop_column("investigation_runs", "lease_expires_at")
    op.drop_column("investigation_runs", "worker_id")
