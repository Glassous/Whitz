"""add private posts feed, AI daily post runs, comments, and delayed AI interactions

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Opt-in AI posts preference on users (default disabled to avoid unexpected credit usage)
    op.add_column(
        "users",
        sa.Column("ai_posts_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("ai_posts_consented_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Daily AI auto-post batch runs (per-user per-local-date idempotency lock)
    op.create_table(
        "ai_post_daily_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("tier", sa.String(length=16), server_default="free", nullable=False),
        sa.Column("memory_entry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active_collection_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("target_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="running", nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "local_date", name="uq_ai_post_daily_runs_user_date"),
    )
    op.create_index("ix_ai_post_daily_runs_user_id", "ai_post_daily_runs", ["user_id"])
    op.create_index("ix_ai_post_daily_runs_user_date", "ai_post_daily_runs", ["user_id", "local_date"])

    # 3. Private posts table (strictly per-user; author_type='ai' or 'user')
    op.create_table(
        "posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_type", sa.String(length=16), server_default="ai", nullable=False),
        sa.Column("post_kind", sa.String(length=24), server_default="opinion", nullable=False),
        sa.Column("title", sa.String(length=120), server_default="", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("web_sources", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column(
            "source_collection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memory_collections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_collection_name", sa.String(length=80), nullable=True),
        sa.Column(
            "source_memory_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "memory_entry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memory_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_liked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ai_liked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_bookmarked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "daily_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_post_daily_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_posts_user_id", "posts", ["user_id"])
    op.create_index("ix_posts_user_created", "posts", ["user_id", "created_at"])
    op.create_index("ix_posts_user_author_created", "posts", ["user_id", "author_type", "created_at"])
    op.create_index("ix_posts_user_bookmarked", "posts", ["user_id", "is_bookmarked", "created_at"])

    # 4. Post comments (user comments + AI comments + threaded replies)
    op.create_table(
        "post_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_type", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "reply_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_comments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ai_liked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_post_comments_post_id", "post_comments", ["post_id"])
    op.create_index("ix_post_comments_user_id", "post_comments", ["user_id"])
    op.create_index("ix_post_comments_post_created", "post_comments", ["post_id", "created_at"])

    # 5. Persistent delayed AI interaction queue (realistic non-instant likes & comments)
    op.create_table(
        "ai_post_pending_interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "trigger_comment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("post_comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_post_interactions_user", "ai_post_pending_interactions", ["user_id"])
    op.create_index("ix_ai_post_interactions_due", "ai_post_pending_interactions", ["status", "scheduled_for"])


def downgrade() -> None:
    op.drop_index("ix_ai_post_interactions_due", table_name="ai_post_pending_interactions")
    op.drop_index("ix_ai_post_interactions_user", table_name="ai_post_pending_interactions")
    op.drop_table("ai_post_pending_interactions")

    op.drop_index("ix_post_comments_post_created", table_name="post_comments")
    op.drop_index("ix_post_comments_user_id", table_name="post_comments")
    op.drop_index("ix_post_comments_post_id", table_name="post_comments")
    op.drop_table("post_comments")

    op.drop_index("ix_posts_user_bookmarked", table_name="posts")
    op.drop_index("ix_posts_user_author_created", table_name="posts")
    op.drop_index("ix_posts_user_created", table_name="posts")
    op.drop_index("ix_posts_user_id", table_name="posts")
    op.drop_table("posts")

    op.drop_index("ix_ai_post_daily_runs_user_date", table_name="ai_post_daily_runs")
    op.drop_index("ix_ai_post_daily_runs_user_id", table_name="ai_post_daily_runs")
    op.drop_table("ai_post_daily_runs")

    op.drop_column("users", "ai_posts_consented_at")
    op.drop_column("users", "ai_posts_enabled")
