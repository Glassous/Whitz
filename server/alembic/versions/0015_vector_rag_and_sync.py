"""add episodic message_chunks vectorization, pg_trgm CJK indexes, file index_status, and pending_control sync

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


class _VectorCol(UserDefinedType):
    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"VECTOR({self.dim})"


def _ensure_extension(ext_name: str) -> bool:
    conn = op.get_bind()
    sp = f"sp_ext_{ext_name}_0015"
    try:
        conn.execute(sa.text(f"SAVEPOINT {sp}"))
        res = conn.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = :name"), {"name": ext_name}).scalar()
        if not res:
            conn.execute(sa.text(f"CREATE EXTENSION IF NOT EXISTS {ext_name}"))
        conn.execute(sa.text(f"RELEASE SAVEPOINT {sp}"))
        return True
    except Exception:
        conn.execute(sa.text(f"ROLLBACK TO SAVEPOINT {sp}"))
        return False


def upgrade() -> None:
    has_vector = _ensure_extension("vector")
    has_trgm = _ensure_extension("pg_trgm")
    emb_type = _VectorCol(1536) if has_vector else postgresql.JSONB()

    # 1. Conversation pending_control snapshot for multi-device HITL sync
    op.add_column(
        "conversations",
        sa.Column("pending_control", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # 2. File async indexing telemetry columns
    op.add_column(
        "conversation_files",
        sa.Column("index_status", sa.String(length=24), server_default="ready", nullable=False),
    )
    op.add_column(
        "conversation_files",
        sa.Column("indexed_chunks", sa.Integer(), server_default="0", nullable=False),
    )

    # 3. Contextual header on file_chunks
    op.add_column(
        "file_chunks",
        sa.Column("context_header", sa.Text(), server_default="", nullable=False),
    )

    # 4. Composite indexes on messages for fast paginated history & run lookup
    op.create_index("ix_messages_conv_created", "messages", ["conversation_id", "created_at"])
    op.create_index("ix_messages_conv_run", "messages", ["conversation_id", "run_id"])

    # 5. Episodic turn-level semantic chunks table (message_chunks)
    op.create_table(
        "message_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_kind", sa.String(length=16), server_default="side", nullable=False),
        sa.Column("start_msg_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("end_msg_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context_header", sa.Text(), server_default="", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding", emb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_message_chunks_user_id", "message_chunks", ["user_id"])
    op.create_index("ix_message_chunks_conversation_id", "message_chunks", ["conversation_id"])
    op.create_index("ix_message_chunks_start_msg_id", "message_chunks", ["start_msg_id"])
    op.create_index("ix_message_chunks_user_conv", "message_chunks", ["user_id", "conversation_id", "created_at"])
    op.create_index("ix_message_chunks_search_tsv", "message_chunks", ["search_tsv"], postgresql_using="gin")

    if has_vector:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_message_chunks_embedding_hnsw "
            "ON message_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )

    # 6. pg_trgm GIN indexes for fast CJK substring & fuzzy similarity search
    if has_trgm:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_file_chunks_content_trgm "
            "ON file_chunks USING gin (content gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_message_chunks_content_trgm "
            "ON message_chunks USING gin (content gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_conversation_digests_summary_trgm "
            "ON conversation_digests USING gin (summary gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memory_entries_content_trgm "
            "ON memory_entries USING gin (content gin_trgm_ops)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_entries_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_conversation_digests_summary_trgm")
    op.execute("DROP INDEX IF EXISTS ix_message_chunks_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_file_chunks_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_message_chunks_embedding_hnsw")
    op.drop_index("ix_message_chunks_search_tsv", table_name="message_chunks")
    op.drop_index("ix_message_chunks_user_conv", table_name="message_chunks")
    op.drop_index("ix_message_chunks_start_msg_id", table_name="message_chunks")
    op.drop_index("ix_message_chunks_conversation_id", table_name="message_chunks")
    op.drop_index("ix_message_chunks_user_id", table_name="message_chunks")
    op.drop_table("message_chunks")

    op.drop_index("ix_messages_conv_run", table_name="messages")
    op.drop_index("ix_messages_conv_created", table_name="messages")

    op.drop_column("file_chunks", "context_header")
    op.drop_column("conversation_files", "indexed_chunks")
    op.drop_column("conversation_files", "index_status")
    op.drop_column("conversations", "pending_control")
