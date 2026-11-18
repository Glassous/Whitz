"""add desktop llm keys

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_llm_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_desktop_llm_keys_user_id", "desktop_llm_keys", ["user_id"])
    op.create_index("ix_desktop_llm_keys_token_hash", "desktop_llm_keys", ["token_hash"], unique=True)
    op.create_index("ix_desktop_llm_keys_user", "desktop_llm_keys", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_desktop_llm_keys_user", table_name="desktop_llm_keys")
    op.drop_index("ix_desktop_llm_keys_token_hash", table_name="desktop_llm_keys")
    op.drop_index("ix_desktop_llm_keys_user_id", table_name="desktop_llm_keys")
    op.drop_table("desktop_llm_keys")
