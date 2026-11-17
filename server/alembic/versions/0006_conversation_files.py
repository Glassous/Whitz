"""add conversation_files workspace table

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("ext", sa.String(24), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("etag", sa.String(128), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversation_files_conversation_id", "conversation_files", ["conversation_id"])
    op.create_index("ix_conversation_files_user_id", "conversation_files", ["user_id"])
    op.create_index(
        "ix_conversation_files_conv_created",
        "conversation_files",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_files_conv_created", table_name="conversation_files")
    op.drop_index("ix_conversation_files_user_id", table_name="conversation_files")
    op.drop_index("ix_conversation_files_conversation_id", table_name="conversation_files")
    op.drop_table("conversation_files")
