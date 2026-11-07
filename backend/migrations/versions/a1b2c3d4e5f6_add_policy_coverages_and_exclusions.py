"""Add policy_coverages and policy_exclusions tables for policy administration.

Revision ID: a1b2c3d4e5f6
Revises: f4a1b2c3d4e5
Create Date: 2026-11-04 01:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f4a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create policy_coverages table
    op.create_table(
        'policy_coverages',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('policy_documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'coverage_name',
            sa.String(length=150),
            nullable=False,
        ),
        sa.Column(
            'coverage_category',
            sa.String(length=50),
            server_default='inpatient',
            nullable=False,
        ),
        sa.Column(
            'benefit_limit',
            sa.Numeric(precision=14, scale=2),
            nullable=True,
        ),
        sa.Column(
            'deductible',
            sa.Numeric(precision=14, scale=2),
            nullable=True,
        ),
        sa.Column(
            'co_pay_percentage',
            sa.Numeric(precision=5, scale=2),
            nullable=True,
        ),
        sa.Column(
            'waiting_period_days',
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            'description',
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            'is_optional',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            'benefit_limit IS NULL OR benefit_limit >= 0',
            name='ck_policy_coverages_benefit_limit_nonnegative',
        ),
        sa.CheckConstraint(
            'deductible IS NULL OR deductible >= 0',
            name='ck_policy_coverages_deductible_nonnegative',
        ),
        sa.CheckConstraint(
            'co_pay_percentage IS NULL OR (co_pay_percentage >= 0 AND co_pay_percentage <= 100)',
            name='ck_policy_coverages_co_pay_percentage_range',
        ),
        sa.CheckConstraint(
            'waiting_period_days IS NULL OR waiting_period_days >= 0',
            name='ck_policy_coverages_waiting_period_nonnegative',
        ),
        sa.CheckConstraint(
            'length(trim(coverage_name)) > 0',
            name='ck_policy_coverages_name_nonempty',
        ),
    )
    op.create_index(
        'ix_policy_coverages_document_id',
        'policy_coverages',
        ['document_id'],
        unique=False,
    )
    op.create_index(
        'ix_policy_coverages_category',
        'policy_coverages',
        ['coverage_category'],
        unique=False,
    )

    # 2. Create policy_exclusions table
    op.create_table(
        'policy_exclusions',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'document_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('policy_documents.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'exclusion_code',
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column(
            'title',
            sa.String(length=200),
            nullable=False,
        ),
        sa.Column(
            'description',
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            'waiting_period_months',
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            'exclusion_type',
            sa.String(length=50),
            server_default='permanent',
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            'waiting_period_months IS NULL OR waiting_period_months >= 0',
            name='ck_policy_exclusions_waiting_period_nonnegative',
        ),
        sa.CheckConstraint(
            'length(trim(title)) > 0',
            name='ck_policy_exclusions_title_nonempty',
        ),
        sa.CheckConstraint(
            'length(trim(description)) > 0',
            name='ck_policy_exclusions_description_nonempty',
        ),
        sa.CheckConstraint(
            "exclusion_type IN ('permanent', 'waiting_period', 'condition_based', 'specified_illness', 'other')",
            name='ck_policy_exclusions_type_valid',
        ),
    )
    op.create_index(
        'ix_policy_exclusions_document_id',
        'policy_exclusions',
        ['document_id'],
        unique=False,
    )
    op.create_index(
        'ix_policy_exclusions_code',
        'policy_exclusions',
        ['exclusion_code'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_policy_exclusions_code', table_name='policy_exclusions')
    op.drop_index('ix_policy_exclusions_document_id', table_name='policy_exclusions')
    op.drop_table('policy_exclusions')

    op.drop_index('ix_policy_coverages_category', table_name='policy_coverages')
    op.drop_index('ix_policy_coverages_document_id', table_name='policy_coverages')
    op.drop_table('policy_coverages')
