"""add 4-tier cognitive context schema: pinned core memories, structured working_state, and immutable conversation_episodes

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def _has_extension(ext_name: str) -> bool:
    conn = op.get_bind()
    try:
        res = conn.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = :name"), {"name": ext_name}).scalar()
        return bool(res)
    except Exception:
        return False


def upgrade() -> None:
    # 1. Structured Working State on conversations (applies to both main and long side chats)
    op.add_column(
        "conversations",
        sa.Column("working_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("working_state_cursor_msg_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("working_state_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. L0 Pinned Core Memory & Lifecycle governance on memory_entries
    op.add_column(
        "memory_entries",
        sa.Column("is_pinned", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "memory_entries",
        sa.Column("priority", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column(
        "memory_entries",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memory_entries",
        sa.Column("access_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "memory_entries",
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_memory_entries_user_pinned",
        "memory_entries",
        ["user_id", "is_pinned", "status"],
    )

    # 3. L2 Immutable Conversation Episodes table (episodic archive for main & long side chats)
    has_vector = _has_extension("vector")
    has_trgm = _has_extension("pg_trgm")

    op.create_table(
        "conversation_episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_kind", sa.String(length=16), server_default="main", nullable=False),
        sa.Column("episode_index", sa.Integer(), server_default="1", nullable=False),
        sa.Column("topic", sa.String(length=200), server_default="", nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("key_facts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("start_msg_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("end_msg_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversation_episodes_user_id", "conversation_episodes", ["user_id"])
    op.create_index(
        "ix_conversation_episodes_conv_idx",
        "conversation_episodes",
        ["conversation_id", "episode_index"],
    )
    op.create_index(
        "ix_conversation_episodes_user_ended",
        "conversation_episodes",
        ["user_id", "ended_at"],
    )
    op.create_index(
        "ix_conversation_episodes_search_tsv",
        "conversation_episodes",
        ["search_tsv"],
        postgresql_using="gin",
    )

    if has_vector:
        op.execute("ALTER TABLE conversation_episodes ADD COLUMN embedding vector(1536)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_conversation_episodes_embedding_hnsw "
            "ON conversation_episodes USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    else:
        op.add_column(
            "conversation_episodes",
            sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )

    if has_trgm:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_conversation_episodes_summary_trgm "
            "ON conversation_episodes USING gin (summary gin_trgm_ops)"
        )


def downgrade() -> None:
    op.drop_table("conversation_episodes")
    op.drop_index("ix_memory_entries_user_pinned", table_name="memory_entries")
    op.drop_column("memory_entries", "supersedes_id")
    op.drop_column("memory_entries", "access_count")
    op.drop_column("memory_entries", "last_accessed_at")
    op.drop_column("memory_entries", "priority")
    op.drop_column("memory_entries", "is_pinned")
    op.drop_column("conversations", "working_state_updated_at")
    op.drop_column("conversations", "working_state_cursor_msg_id")
    op.drop_column("conversations", "working_state")
