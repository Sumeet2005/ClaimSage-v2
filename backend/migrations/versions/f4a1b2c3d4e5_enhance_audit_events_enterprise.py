"""Enhance audit_events with enterprise actor, category, scoping, and metadata columns.

Revision ID: f4a1b2c3d4e5
Revises: e3c5a7b9d1f2
Create Date: 2026-11-03 23:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f4a1b2c3d4e5'
down_revision: Union[str, None] = 'e3c5a7b9d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive columns with server defaults for backward compatibility
    op.add_column(
        'audit_events',
        sa.Column(
            'actor_type',
            sa.String(length=30),
            server_default='employee',
            nullable=False,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'actor_id',
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'claim_id',
            sa.UUID(),
            nullable=True,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'investigation_id',
            sa.UUID(),
            nullable=True,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'event_category',
            sa.String(length=50),
            server_default='claim',
            nullable=False,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'outcome',
            sa.String(length=20),
            server_default='success',
            nullable=False,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'event_metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'audit_events',
        sa.Column(
            'correlation_id',
            sa.String(length=100),
            nullable=True,
        ),
    )

    # Foreign key constraints
    op.create_foreign_key(
        'fk_audit_events_claim_id_claims',
        'audit_events',
        'claims',
        ['claim_id'],
        ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_audit_events_investigation_id_runs',
        'audit_events',
        'investigation_runs',
        ['investigation_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # Indices for high-performance timeline retrieval and filtering
    op.create_index(
        'ix_audit_events_claim_created',
        'audit_events',
        ['claim_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_audit_events_investigation_created',
        'audit_events',
        ['investigation_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_audit_events_category',
        'audit_events',
        ['event_category'],
        unique=False,
    )
    op.create_index(
        'ix_audit_events_actor_type',
        'audit_events',
        ['actor_type'],
        unique=False,
    )
    op.create_index(
        'ix_audit_events_correlation',
        'audit_events',
        ['correlation_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_audit_events_correlation', table_name='audit_events')
    op.drop_index('ix_audit_events_actor_type', table_name='audit_events')
    op.drop_index('ix_audit_events_category', table_name='audit_events')
    op.drop_index('ix_audit_events_investigation_created', table_name='audit_events')
    op.drop_index('ix_audit_events_claim_created', table_name='audit_events')

    op.drop_constraint('fk_audit_events_investigation_id_runs', 'audit_events', type_='foreignkey')
    op.drop_constraint('fk_audit_events_claim_id_claims', 'audit_events', type_='foreignkey')

    op.drop_column('audit_events', 'correlation_id')
    op.drop_column('audit_events', 'event_metadata')
    op.drop_column('audit_events', 'outcome')
    op.drop_column('audit_events', 'event_category')
    op.drop_column('audit_events', 'investigation_id')
    op.drop_column('audit_events', 'claim_id')
    op.drop_column('audit_events', 'actor_id')
    op.drop_column('audit_events', 'actor_type')
