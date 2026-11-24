"""add unified RAG schema extensions: file summaries, chunk structure metadata, embedding_model versions, and rag_metrics

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
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
    # 1. ConversationFile document-level summary & index diagnostics
    op.add_column(
        "conversation_files",
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "conversation_files",
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column(
        "conversation_files",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "conversation_files",
        sa.Column("index_error", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "conversation_files",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. FileChunk structural hierarchy, chunk_type, metadata, and model version
    op.add_column(
        "file_chunks",
        sa.Column("section_path", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "file_chunks",
        sa.Column("chunk_type", sa.String(length=24), server_default="text", nullable=False),
    )
    op.add_column(
        "file_chunks",
        sa.Column("token_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "file_chunks",
        sa.Column("chunk_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "file_chunks",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.create_index("ix_file_chunks_file_idx", "file_chunks", ["file_id", "chunk_index"])

    # 3. Embedding model versioning across memory_entries, conversation_digests, message_chunks
    op.add_column(
        "memory_entries",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "conversation_digests",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "message_chunks",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )

    # 4. RunTelemetry RAG observability metrics
    op.add_column(
        "run_telemetry",
        sa.Column("rag_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # 5. Ensure HNSW indexes exist across all 4 vector tables when pgvector is available
    if _has_extension("vector"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_file_chunks_embedding_hnsw "
            "ON file_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding_hnsw "
            "ON memory_entries USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_conversation_digests_embedding_hnsw "
            "ON conversation_digests USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_message_chunks_embedding_hnsw "
            "ON message_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    op.drop_column("run_telemetry", "rag_metrics")
    op.drop_column("message_chunks", "embedding_model")
    op.drop_column("conversation_digests", "embedding_model")
    op.drop_column("memory_entries", "embedding_model")

    op.drop_index("ix_file_chunks_file_idx", table_name="file_chunks")
    op.drop_column("file_chunks", "embedding_model")
    op.drop_column("file_chunks", "chunk_meta")
    op.drop_column("file_chunks", "token_count")
    op.drop_column("file_chunks", "chunk_type")
    op.drop_column("file_chunks", "section_path")

    op.drop_column("conversation_files", "indexed_at")
    op.drop_column("conversation_files", "index_error")
    op.drop_column("conversation_files", "embedding_model")
    op.drop_column("conversation_files", "keywords")
    op.drop_column("conversation_files", "summary")
