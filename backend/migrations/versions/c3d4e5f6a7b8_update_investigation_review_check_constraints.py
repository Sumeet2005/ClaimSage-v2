"""Update investigation review and run check constraints to support all six human review decisions.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-10 19:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPANDED_REVIEW_STATUSES = (
    "'pending', 'reviewed', 'needs_follow_up', 'escalated', "
    "'approved', 'needs_additional_documents', 'returned_for_investigation'"
)
EXPANDED_REVIEW_DECISIONS = (
    "'reviewed', 'needs_follow_up', 'escalated', "
    "'approved', 'needs_additional_documents', 'returned_for_investigation'"
)

LEGACY_REVIEW_STATUSES = "'pending', 'reviewed', 'needs_follow_up', 'escalated'"
LEGACY_REVIEW_DECISIONS = "'reviewed', 'needs_follow_up', 'escalated'"


def upgrade() -> None:
    """Expand check constraints to support approved, needs_additional_documents, and returned_for_investigation."""
    # 1. Update investigation_runs check constraint
    op.drop_constraint(
        "ck_investigation_runs_review_status_valid",
        "investigation_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_investigation_runs_review_status_valid",
        "investigation_runs",
        f"human_review_status IN ({EXPANDED_REVIEW_STATUSES})",
    )

    # 2. Update investigation_reviews check constraint
    op.drop_constraint(
        "ck_investigation_reviews_decision_valid",
        "investigation_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_investigation_reviews_decision_valid",
        "investigation_reviews",
        f"decision IN ({EXPANDED_REVIEW_DECISIONS})",
    )


def downgrade() -> None:
    """Restore legacy check constraints on investigation_runs and investigation_reviews."""
    op.drop_constraint(
        "ck_investigation_reviews_decision_valid",
        "investigation_reviews",
        type_="check",
    )
    op.create_check_constraint(
        "ck_investigation_reviews_decision_valid",
        "investigation_reviews",
        f"decision IN ({LEGACY_REVIEW_DECISIONS})",
    )

    op.drop_constraint(
        "ck_investigation_runs_review_status_valid",
        "investigation_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_investigation_runs_review_status_valid",
        "investigation_runs",
        f"human_review_status IN ({LEGACY_REVIEW_STATUSES})",
    )
