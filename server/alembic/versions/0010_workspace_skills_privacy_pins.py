"""add workspace privacy flags, conversation pins, and file library fields

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("profile_context_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("profile_context_consented_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("memory_consented_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("memory_require_confirm", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.add_column(
        "conversations",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "conversations",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversations_is_pinned", "conversations", ["is_pinned"])

    op.alter_column(
        "conversation_files",
        "conversation_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.drop_constraint(
        "conversation_files_conversation_id_fkey",
        "conversation_files",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "conversation_files_conversation_id_fkey",
        "conversation_files",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "conversation_files",
        sa.Column("source", sa.String(24), nullable=False, server_default="user"),
    )
    op.add_column(
        "conversation_files",
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_conversation_files_is_global", "conversation_files", ["is_global"])
    op.add_column(
        "conversation_files",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_conversation_files_message_id", "conversation_files", ["message_id"])
    op.add_column(
        "conversation_files",
        sa.Column("expires_cleanup_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_files", "expires_cleanup_at")
    op.drop_index("ix_conversation_files_message_id", table_name="conversation_files")
    op.drop_column("conversation_files", "message_id")
    op.drop_index("ix_conversation_files_is_global", table_name="conversation_files")
    op.drop_column("conversation_files", "is_global")
    op.drop_column("conversation_files", "source")
    op.drop_constraint(
        "conversation_files_conversation_id_fkey",
        "conversation_files",
        type_="foreignkey",
    )
    op.execute("DELETE FROM conversation_files WHERE conversation_id IS NULL")
    op.alter_column(
        "conversation_files",
        "conversation_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "conversation_files_conversation_id_fkey",
        "conversation_files",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index("ix_conversations_is_pinned", table_name="conversations")
    op.drop_column("conversations", "pinned_at")
    op.drop_column("conversations", "is_pinned")

    op.drop_column("users", "memory_require_confirm")
    op.drop_column("users", "memory_consented_at")
    op.drop_column("users", "memory_enabled")
    op.drop_column("users", "profile_context_consented_at")
    op.drop_column("users", "profile_context_enabled")
