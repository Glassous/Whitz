"""remove hermes and add langgraph tables

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


class _VectorCol(UserDefinedType):
    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"VECTOR({self.dim})"


def _try_enable_pgvector() -> bool:
    conn = op.get_bind()
    try:
        conn.execute(sa.text("SAVEPOINT sp_pgvector"))
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(sa.text("RELEASE SAVEPOINT sp_pgvector"))
        return True
    except Exception:
        conn.execute(sa.text("ROLLBACK TO SAVEPOINT sp_pgvector"))
        return False


def upgrade() -> None:
    has_vector = _try_enable_pgvector()
    emb_type = _VectorCol(1536) if has_vector else postgresql.JSONB()

    op.alter_column("users", "hermes_profile", new_column_name="agent_namespace")
    op.alter_column("users", "hermes_api_key", new_column_name="agent_api_key")
    op.execute(sa.text("ALTER INDEX IF EXISTS ix_users_hermes_profile RENAME TO ix_users_agent_namespace"))

    op.alter_column("conversations", "hermes_session_id", new_column_name="thread_id")
    op.alter_column(
        "conversations",
        "thread_id",
        existing_type=sa.String(length=128),
        server_default="",
    )

    op.alter_column("messages", "hermes_run_id", new_column_name="run_id")

    op.create_table(
        "memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target", sa.String(length=16), server_default="memory", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=24), server_default="manual", nullable=False),
        sa.Column("embedding", emb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_entries_user_id", "memory_entries", ["user_id"])
    op.create_index("ix_memory_entries_user_target", "memory_entries", ["user_id", "target"])

    op.create_table(
        "memory_pending_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target", sa.String(length=16), server_default="memory", nullable=False),
        sa.Column("action", sa.String(length=16), server_default="add", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("old_content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_pending_proposals_user_id", "memory_pending_proposals", ["user_id"])
    op.create_index("ix_memory_pending_proposals_status", "memory_pending_proposals", ["status"])
    op.create_index(
        "ix_memory_pending_user_status",
        "memory_pending_proposals",
        ["user_id", "status", "created_at"],
    )

    op.create_table(
        "user_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("source", sa.String(length=24), server_default="custom", nullable=False),
        sa.Column("repo_url", sa.String(length=500), nullable=True),
        sa.Column("ref", sa.String(length=120), nullable=True),
        sa.Column("path", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_skills_user_name"),
    )
    op.create_index("ix_user_skills_user_id", "user_skills", ["user_id"])
    op.create_index("ix_user_skills_user_enabled", "user_skills", ["user_id", "enabled"])

    op.create_table(
        "skill_pending_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=True),
        sa.Column("action", sa.String(length=24), server_default="create", nullable=False),
        sa.Column("source", sa.String(length=24), server_default="agent", nullable=False),
        sa.Column("repo_url", sa.String(length=500), nullable=True),
        sa.Column("ref", sa.String(length=120), nullable=True),
        sa.Column("path", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_pending_proposals_user_id", "skill_pending_proposals", ["user_id"])
    op.create_index("ix_skill_pending_proposals_status", "skill_pending_proposals", ["status"])
    op.create_index(
        "ix_skill_pending_user_status",
        "skill_pending_proposals",
        ["user_id", "status", "created_at"],
    )

    op.create_table(
        "file_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_global", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=160), server_default="", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding", emb_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["conversation_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_chunks_file_id", "file_chunks", ["file_id"])
    op.create_index("ix_file_chunks_conversation_id", "file_chunks", ["conversation_id"])
    op.create_index("ix_file_chunks_user_id", "file_chunks", ["user_id"])
    op.create_index("ix_file_chunks_is_global", "file_chunks", ["is_global"])
    op.create_index("ix_file_chunks_user_conv", "file_chunks", ["user_id", "conversation_id"])
    op.create_index("ix_file_chunks_search_tsv", "file_chunks", ["search_tsv"], postgresql_using="gin")

    if has_vector:
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_file_chunks_embedding_hnsw "
                "ON file_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_memory_entries_embedding_hnsw "
                "ON memory_entries USING hnsw (embedding vector_cosine_ops)"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_memory_entries_embedding_hnsw"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_file_chunks_embedding_hnsw"))
    op.drop_index("ix_file_chunks_search_tsv", table_name="file_chunks")
    op.drop_index("ix_file_chunks_user_conv", table_name="file_chunks")
    op.drop_index("ix_file_chunks_is_global", table_name="file_chunks")
    op.drop_index("ix_file_chunks_user_id", table_name="file_chunks")
    op.drop_index("ix_file_chunks_conversation_id", table_name="file_chunks")
    op.drop_index("ix_file_chunks_file_id", table_name="file_chunks")
    op.drop_table("file_chunks")

    op.drop_index("ix_skill_pending_user_status", table_name="skill_pending_proposals")
    op.drop_index("ix_skill_pending_proposals_status", table_name="skill_pending_proposals")
    op.drop_index("ix_skill_pending_proposals_user_id", table_name="skill_pending_proposals")
    op.drop_table("skill_pending_proposals")

    op.drop_index("ix_user_skills_user_enabled", table_name="user_skills")
    op.drop_index("ix_user_skills_user_id", table_name="user_skills")
    op.drop_table("user_skills")

    op.drop_index("ix_memory_pending_user_status", table_name="memory_pending_proposals")
    op.drop_index("ix_memory_pending_proposals_status", table_name="memory_pending_proposals")
    op.drop_index("ix_memory_pending_proposals_user_id", table_name="memory_pending_proposals")
    op.drop_table("memory_pending_proposals")

    op.drop_index("ix_memory_entries_user_target", table_name="memory_entries")
    op.drop_index("ix_memory_entries_user_id", table_name="memory_entries")
    op.drop_table("memory_entries")

    op.alter_column("messages", "run_id", new_column_name="hermes_run_id")
    op.alter_column(
        "conversations",
        "thread_id",
        existing_type=sa.String(length=128),
        server_default=None,
    )
    op.alter_column("conversations", "thread_id", new_column_name="hermes_session_id")
    op.execute(sa.text("ALTER INDEX IF EXISTS ix_users_agent_namespace RENAME TO ix_users_hermes_profile"))
    op.alter_column("users", "agent_api_key", new_column_name="hermes_api_key")
    op.alter_column("users", "agent_namespace", new_column_name="hermes_profile")
