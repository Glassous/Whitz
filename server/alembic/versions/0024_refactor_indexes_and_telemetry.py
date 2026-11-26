"""refactor indexes, credit bucket/idempotency, file provenance, and lightweight tool_invocations table

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Prevent UsageDaily.tokens 32-bit overflow
    op.alter_column(
        "usage_daily",
        "tokens",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    # 2. CreditLedger: separate non-expiring bonus bucket + non-chat idempotency source_ref
    op.add_column(
        "credit_ledger",
        sa.Column("bucket", sa.String(length=16), nullable=False, server_default="plan"),
    )
    op.add_column(
        "credit_ledger",
        sa.Column("source_ref", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "uq_credit_ledger_source_ref",
        "credit_ledger",
        ["source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )

    # 3. Conversation: active_run partial index + explicit is_scheduled & memory_excluded flags
    op.add_column(
        "conversations",
        sa.Column("is_scheduled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "conversations",
        sa.Column("memory_excluded", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_conversations_active_run",
        "conversations",
        ["active_run_id"],
        postgresql_where=sa.text("active_run_id IS NOT NULL"),
    )

    # 4. ConversationFile: track last_edited_by without overwriting original user source
    op.add_column(
        "conversation_files",
        sa.Column("last_edited_by", sa.String(length=24), nullable=True),
    )

    # 5. Lightweight indexed tool_invocations table for Ops & Admin telemetry
    op.create_table(
        "tool_invocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tool_invocations_user_id", "tool_invocations", ["user_id"])
    op.create_index("ix_tool_invocations_name_created", "tool_invocations", ["tool_name", "created_at"])
    op.create_index("ix_tool_invocations_user_created", "tool_invocations", ["user_id", "created_at"])
    op.create_index("ix_tool_invocations_run", "tool_invocations", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_invocations_run", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_user_created", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_name_created", table_name="tool_invocations")
    op.drop_index("ix_tool_invocations_user_id", table_name="tool_invocations")
    op.drop_table("tool_invocations")

    op.drop_column("conversation_files", "last_edited_by")

    op.drop_index("ix_conversations_active_run", table_name="conversations")
    op.drop_column("conversations", "memory_excluded")
    op.drop_column("conversations", "is_scheduled")

    op.drop_index("uq_credit_ledger_source_ref", table_name="credit_ledger")
    op.drop_column("credit_ledger", "source_ref")
    op.drop_column("credit_ledger", "bucket")

    op.alter_column(
        "usage_daily",
        "tokens",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
