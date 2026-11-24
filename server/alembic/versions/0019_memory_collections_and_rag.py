"""add memory_collections and hybrid RAG columns on memory_entries

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_collections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=300), server_default="", nullable=False),
        sa.Column("kind", sa.String(length=24), server_default="custom", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("char_limit", sa.Integer(), server_default="12000", nullable=False),
        sa.Column("max_entries", sa.Integer(), server_default="200", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="100", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "slug", name="uq_memory_collections_user_slug"),
    )
    op.create_index("ix_memory_collections_user_id", "memory_collections", ["user_id"])
    op.create_index("ix_memory_collections_user_enabled", "memory_collections", ["user_id", "enabled"])

    # Extend memory_entries
    op.add_column(
        "memory_entries",
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "memory_entries_collection_id_fkey",
        "memory_entries",
        "memory_collections",
        ["collection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_memory_entries_collection_id", "memory_entries", ["collection_id"])
    op.create_index("ix_memory_entries_user_collection", "memory_entries", ["user_id", "collection_id"])

    op.alter_column(
        "memory_entries",
        "target",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "memory_entries",
        sa.Column("title", sa.String(length=120), server_default="", nullable=False),
    )
    op.add_column(
        "memory_entries",
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column(
        "memory_entries",
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=True),
    )
    op.create_index("ix_memory_entries_search_tsv", "memory_entries", ["search_tsv"], postgresql_using="gin")

    # Extend memory_pending_proposals
    op.add_column(
        "memory_pending_proposals",
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "memory_pending_proposals_collection_id_fkey",
        "memory_pending_proposals",
        "memory_collections",
        ["collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column(
        "memory_pending_proposals",
        "target",
        existing_type=sa.String(length=16),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.add_column(
        "memory_pending_proposals",
        sa.Column("title", sa.String(length=120), server_default="", nullable=False),
    )
    op.add_column(
        "memory_pending_proposals",
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )

    # Seed default system collections for all existing users and backfill collection_id & search_tsv
    op.execute(
        sa.text(
            """
            INSERT INTO memory_collections (id, user_id, slug, name, description, kind, enabled, char_limit, max_entries, sort_order)
            SELECT gen_random_uuid(), u.id, v.slug, v.name, v.description, 'system', true, v.char_limit, 200, v.sort_order
            FROM users u
            CROSS JOIN (
                VALUES
                    ('memory', '通用笔记', '跨对话沉淀的事实、约定、方法论与通用记录', 12000, 10),
                    ('user', '个人画像与偏好', '用户的身份背景、沟通风格、技术栈与长期偏好', 8000, 20),
                    ('projects', '项目与工作', '进行中的项目架构、决策、路径与工作流上下文', 16000, 30)
            ) AS v(slug, name, description, char_limit, sort_order)
            ON CONFLICT (user_id, slug) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE memory_entries me
            SET collection_id = mc.id
            FROM memory_collections mc
            WHERE mc.user_id = me.user_id
              AND mc.slug = CASE
                  WHEN lower(me.target) IN ('user', 'user.md', 'profile') THEN 'user'
                  ELSE 'memory'
              END
              AND me.collection_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE memory_entries
            SET search_tsv = to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))
            WHERE search_tsv IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("memory_pending_proposals", "tags")
    op.drop_column("memory_pending_proposals", "title")
    op.alter_column(
        "memory_pending_proposals",
        "target",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.drop_constraint("memory_pending_proposals_collection_id_fkey", "memory_pending_proposals", type_="foreignkey")
    op.drop_column("memory_pending_proposals", "collection_id")

    op.drop_index("ix_memory_entries_search_tsv", table_name="memory_entries")
    op.drop_column("memory_entries", "search_tsv")
    op.drop_column("memory_entries", "tags")
    op.drop_column("memory_entries", "title")
    op.alter_column(
        "memory_entries",
        "target",
        existing_type=sa.String(length=64),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.drop_index("ix_memory_entries_user_collection", table_name="memory_entries")
    op.drop_index("ix_memory_entries_collection_id", table_name="memory_entries")
    op.drop_constraint("memory_entries_collection_id_fkey", "memory_entries", type_="foreignkey")
    op.drop_column("memory_entries", "collection_id")

    op.drop_index("ix_memory_collections_user_enabled", table_name="memory_collections")
    op.drop_index("ix_memory_collections_user_id", table_name="memory_collections")
    op.drop_table("memory_collections")
