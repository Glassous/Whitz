"""auth sessions and token versioning

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("refresh_tokens", sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("refresh_tokens", sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("refresh_tokens", sa.Column("user_agent", sa.String(256), nullable=True))
    op.add_column("refresh_tokens", sa.Column("client_ip", sa.String(64), nullable=True))
    op.add_column("refresh_tokens", sa.Column("replaced_by_hash", sa.String(64), nullable=True))
    op.add_column("refresh_tokens", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refresh_tokens", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))

    # Existing rows get a session/family of their own so old persisted logins stay valid.
    op.execute("UPDATE refresh_tokens SET session_id = id, family_id = id WHERE session_id IS NULL")

    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "rotated_at")
    op.drop_column("refresh_tokens", "last_used_at")
    op.drop_column("refresh_tokens", "replaced_by_hash")
    op.drop_column("refresh_tokens", "client_ip")
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_column("refresh_tokens", "family_id")
    op.drop_column("refresh_tokens", "session_id")
    op.drop_column("users", "token_version")
