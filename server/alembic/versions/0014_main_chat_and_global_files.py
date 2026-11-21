"""add main chat mode, assistant customization, global files, and conversation digests

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-21
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


class _VectorCol(UserDefinedType):
    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"VECTOR({self.dim})"


def _has_pgvector() -> bool:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("SAVEPOINT sp_pgvector_0014"))
        res = conn.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
        if not res:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(sa.text("RELEASE SAVEPOINT sp_pgvector_0014"))
        return True
    except Exception:
        conn.execute(sa.text("ROLLBACK TO SAVEPOINT sp_pgvector_0014"))
        return False


def upgrade() -> None:
    has_vector = _has_pgvector()
    emb_type = _VectorCol(1536) if has_vector else postgresql.JSONB()

    # 1. Assistant customization fields on users
    op.add_column(
        "users",
        sa.Column("assistant_name", sa.String(length=80), server_default="Whitz", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("assistant_avatar_url", sa.String(length=500), nullable=True),
    )

    # 2. Main vs side chat kind + rolling compaction summary fields on conversations
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(length=16), server_default="side", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("rolling_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_cursor_msg_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_conversations_kind", "conversations", ["kind"])
    op.create_index(
        "uq_conversations_user_main",
        "conversations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'main'"),
    )

    # 3. Data migration: create exactly one main chat for every existing user
    conn = op.get_bind()
    user_rows = conn.execute(
        sa.text(
            """
            SELECT u.id
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM conversations c
                WHERE c.user_id = u.id AND c.kind = 'main'
            )
            """
        )
    ).fetchall()
    for (uid,) in user_rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO conversations (id, user_id, thread_id, kind, title, is_pinned, created_at, updated_at)
                VALUES (:id, :user_id, :thread_id, 'main', '主要聊天', false, NOW(), NOW())
                """
            ),
            {
                "id": uuid.uuid4(),
                "user_id": uid,
                "thread_id": str(uuid.uuid4()),
            },
        )

    # 4. Promote all existing files & file chunks to globally shared
    op.alter_column(
        "conversation_files",
        "is_global",
        existing_type=sa.Boolean(),
        server_default="true",
        existing_nullable=False,
    )
    op.alter_column(
        "file_chunks",
        "is_global",
        existing_type=sa.Boolean(),
        server_default="true",
        existing_nullable=False,
    )
    op.execute(sa.text("UPDATE conversation_files SET is_global = TRUE WHERE is_global = FALSE"))
    op.execute(sa.text("UPDATE file_chunks SET is_global = TRUE WHERE is_global = FALSE"))

    # 5. Cross-chat episodic digest table for main-chat memory over all side chats
    op.create_table(
        "conversation_digests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), server_default="", nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("key_facts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding", emb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_conversation_digests_conv"),
    )
    op.create_index("ix_conversation_digests_user_id", "conversation_digests", ["user_id"])
    op.create_index("ix_conversation_digests_conversation_id", "conversation_digests", ["conversation_id"])
    op.create_index(
        "ix_conversation_digests_user_recent",
        "conversation_digests",
        ["user_id", "last_message_at"],
    )
    op.create_index(
        "ix_conversation_digests_search_tsv",
        "conversation_digests",
        ["search_tsv"],
        postgresql_using="gin",
    )
    if has_vector:
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_conversation_digests_embedding_hnsw "
                "ON conversation_digests USING hnsw (embedding vector_cosine_ops)"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_conversation_digests_embedding_hnsw"))
    op.drop_index("ix_conversation_digests_search_tsv", table_name="conversation_digests")
    op.drop_index("ix_conversation_digests_user_recent", table_name="conversation_digests")
    op.drop_index("ix_conversation_digests_conversation_id", table_name="conversation_digests")
    op.drop_index("ix_conversation_digests_user_id", table_name="conversation_digests")
    op.drop_table("conversation_digests")

    op.alter_column(
        "file_chunks",
        "is_global",
        existing_type=sa.Boolean(),
        server_default="false",
        existing_nullable=False,
    )
    op.alter_column(
        "conversation_files",
        "is_global",
        existing_type=sa.Boolean(),
        server_default="false",
        existing_nullable=False,
    )

    op.execute(sa.text("DELETE FROM conversations WHERE kind = 'main'"))
    op.drop_index("uq_conversations_user_main", table_name="conversations")
    op.drop_index("ix_conversations_kind", table_name="conversations")
    op.drop_column("conversations", "summary_updated_at")
    op.drop_column("conversations", "summary_cursor_msg_id")
    op.drop_column("conversations", "rolling_summary")
    op.drop_column("conversations", "kind")

    op.drop_column("users", "assistant_avatar_url")
    op.drop_column("users", "assistant_name")
