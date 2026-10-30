
"""add policy document persistence

Revision ID: b4b450be3415
Revises: 2e6e79a7dfcc
Create Date: 2026-10-30 14:50:52.455767

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4b450be3415"
down_revision: str | Sequence[str] | None = "2e6e79a7dfcc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "policy_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_employee_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            server_default="uploaded",
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
            "status IN ('uploaded', 'processing', 'processed', 'failed')",
            name="ck_policy_documents_status_valid",
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0",
            name="ck_policy_documents_file_size_positive",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_employee_id"],
            ["employees.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("checksum_sha256"),
    )

    op.create_index(
        "ix_policy_documents_created_at",
        "policy_documents",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_policy_chunks_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(text) > 0",
            name="ck_policy_chunks_text_nonempty",
        ),
        sa.CheckConstraint(
            "page_number > 0",
            name="ck_policy_chunks_page_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["policy_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id"),
        sa.UniqueConstraint(
            "document_id",
            "page_number",
            "chunk_index",
            name="uq_policy_chunks_document_page_index",
        ),
    )

    op.create_index(
        "ix_policy_chunks_document_id",
        "policy_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        "ix_policy_chunks_document_id",
        table_name="policy_chunks",
    )
    op.drop_table("policy_chunks")

    op.drop_index(
        "ix_policy_documents_created_at",
        table_name="policy_documents",
    )
    op.drop_table("policy_documents")
