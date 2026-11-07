"""Add human review finding edits and customer email workflow tables.

Revision ID: e3c5a7b9d1f2
Revises: e2b4f6a8c0d1
Create Date: 2026-11-03 22:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e3c5a7b9d1f2"
down_revision: str | Sequence[str] | None = "e2b4f6a8c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create finding edits and customer email workflow tables."""
    # 1. Create investigation finding edits table (versioned human overrides)
    op.create_table(
        "investigation_finding_edits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "editor_employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("edited_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_finding_edits_finding_id",
        "investigation_finding_edits",
        ["finding_id", "created_at"],
    )

    # 2. Create customer emails table (drafting, human approval, delivery tracking)
    op.create_table(
        "customer_emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "investigation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investigation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("recipient_name", sa.String(length=200), nullable=False),
        sa.Column("sender_email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("template_key", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="drafted",
            nullable=False,
        ),
        sa.Column(
            "approved_by_employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("secure_upload_token", sa.String(length=100), nullable=True),
        sa.Column("secure_upload_url", sa.String(length=500), nullable=True),
        sa.Column("follow_up_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("last_error_type", sa.String(length=100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_customer_emails_idempotency_key",
        "customer_emails",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_customer_emails_claim_status",
        "customer_emails",
        ["claim_id", "status"],
    )
    op.create_index(
        "ix_customer_emails_deadline",
        "customer_emails",
        ["status", "follow_up_deadline"],
    )


def downgrade() -> None:
    """Drop human review and customer email tables."""
    op.drop_table("customer_emails")
    op.drop_table("investigation_finding_edits")
