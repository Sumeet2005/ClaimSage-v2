"""Add an idempotent email notification outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0c17a2f9b64"
down_revision: str | Sequence[str] | None = "c19a7e4f2b61"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the additive notification delivery table."""
    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column(
            "recipient_employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("application_path", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event_type IN "
            "('claim_received', 'investigation_completed', "
            "'human_review_required', 'additional_evidence_required', "
            "'review_completed')",
            name="ck_notification_deliveries_event_valid",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'delivered', 'sandboxed', 'failed')",
            name="ck_notification_deliveries_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_employee_id"],
            ["employees.id"],
            name="fk_notification_deliveries_employee_id_employees",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_notification_deliveries_idempotency_key",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_status_created_at",
        "notification_deliveries",
        ["status", "created_at"],
    )


def downgrade() -> None:
    """Remove only the notification table introduced by this revision."""
    op.drop_index(
        "ix_notification_deliveries_status_created_at",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
