"""Add persistent investigation, report, finding, and review records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8f4c2d9e761"
down_revision: str | Sequence[str] | None = "71d3a6c85f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable investigation lifecycle tables."""
    op.create_table(
        "investigation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_domain", sa.String(length=20), nullable=False),
        sa.Column(
            "initiated_by_employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="running",
            nullable=False,
        ),
        sa.Column("current_stage", sa.String(length=100), nullable=True),
        sa.Column(
            "human_review_status",
            sa.String(length=30),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "state_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("failure_type", sa.String(length=200), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "claim_domain IN ('auto', 'health', 'other')",
            name="ck_investigation_runs_domain_valid",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'incomplete', 'failed')",
            name="ck_investigation_runs_status_valid",
        ),
        sa.CheckConstraint(
            "human_review_status IN "
            "('pending', 'reviewed', 'needs_follow_up', 'escalated')",
            name="ck_investigation_runs_review_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
            name="fk_investigation_runs_claim_id_claims",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by_employee_id"],
            ["employees.id"],
            name="fk_investigation_runs_initiated_by_employee_id_employees",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investigation_runs_claim_created_at",
        "investigation_runs",
        ["claim_id", "created_at"],
    )
    op.create_index(
        "ix_investigation_runs_status",
        "investigation_runs",
        ["status"],
    )

    op.create_table(
        "investigation_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialist", sa.String(length=50), nullable=False),
        sa.Column("finding_type", sa.String(length=100), nullable=False),
        sa.Column(
            "finding_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
        sa.Column(
            "evidence_references",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "policy_references",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigation_runs.id"],
            name="fk_investigation_findings_investigation_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investigation_findings_run_specialist",
        "investigation_findings",
        ["investigation_id", "specialist"],
    )

    op.create_table(
        "investigation_finding_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column(
            "claim_evidence_chunk_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "policy_chunk_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "policy_clause_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind IN ('claim_evidence', 'policy_chunk', 'policy_clause', "
            "'analyst_output', 'unresolved')",
            name="ck_investigation_finding_references_kind_valid",
        ),
        sa.CheckConstraint(
            "num_nonnulls(claim_evidence_chunk_id, policy_chunk_id, "
            "policy_clause_id) <= 1",
            name="ck_investigation_finding_references_single_source",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["investigation_findings.id"],
            name="fk_investigation_finding_references_finding_id_findings",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["claim_evidence_chunk_id"],
            ["claim_evidence_chunks.id"],
            name="fk_investigation_finding_references_claim_chunk",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["policy_chunk_id"],
            ["policy_chunks.id"],
            name="fk_investigation_finding_references_policy_chunk",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["policy_clause_id"],
            ["policy_clauses.id"],
            name="fk_investigation_finding_references_policy_clause",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investigation_finding_references_finding_id",
        "investigation_finding_references",
        ["finding_id"],
    )

    op.create_table(
        "investigation_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "report_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "human_review_required",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "status IN ('completed', 'incomplete', 'unavailable', 'skipped')",
            name="ck_investigation_reports_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigation_runs.id"],
            name="fk_investigation_reports_investigation_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "investigation_id",
            name="uq_investigation_reports_investigation_id",
        ),
    )

    op.create_table(
        "investigation_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reviewer_employee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('reviewed', 'needs_follow_up', 'escalated')",
            name="ck_investigation_reviews_decision_valid",
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigation_runs.id"],
            name="fk_investigation_reviews_investigation_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_employee_id"],
            ["employees.id"],
            name="fk_investigation_reviews_reviewer_employee_id_employees",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investigation_reviews_run_created_at",
        "investigation_reviews",
        ["investigation_id", "created_at"],
    )


def downgrade() -> None:
    """Remove investigation lifecycle tables in dependency order."""
    op.drop_index(
        "ix_investigation_reviews_run_created_at",
        table_name="investigation_reviews",
    )
    op.drop_table("investigation_reviews")
    op.drop_table("investigation_reports")
    op.drop_index(
        "ix_investigation_finding_references_finding_id",
        table_name="investigation_finding_references",
    )
    op.drop_table("investigation_finding_references")
    op.drop_index(
        "ix_investigation_findings_run_specialist",
        table_name="investigation_findings",
    )
    op.drop_table("investigation_findings")
    op.drop_index(
        "ix_investigation_runs_status",
        table_name="investigation_runs",
    )
    op.drop_index(
        "ix_investigation_runs_claim_created_at",
        table_name="investigation_runs",
    )
    op.drop_table("investigation_runs")
