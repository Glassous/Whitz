"""add audit hash chain, run telemetry signals, message reactions, user feedbacks, and model pricing

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("ai_reactions_enabled", sa.Boolean(), server_default="true", nullable=False),
    )

    op.add_column("audit_logs", sa.Column("risk_score", sa.Integer(), server_default="0", nullable=False))
    op.add_column("audit_logs", sa.Column("diff", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("audit_logs", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("record_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_logs_risk_created", "audit_logs", ["risk_score", "created_at"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"])
    op.create_index("ix_audit_logs_record_hash", "audit_logs", ["record_hash"])

    op.add_column(
        "run_telemetry",
        sa.Column("is_regenerated", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "run_telemetry",
        sa.Column("hitl_denied_count", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "message_reactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_type", sa.String(length=16), server_default="user", nullable=False),
        sa.Column("reaction", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "author_type", "user_id", name="uq_message_reactions_msg_actor_user"),
    )
    op.create_index("ix_message_reactions_message_id", "message_reactions", ["message_id"])
    op.create_index("ix_message_reactions_conversation_id", "message_reactions", ["conversation_id"])
    op.create_index("ix_message_reactions_user_id", "message_reactions", ["user_id"])
    op.create_index("ix_message_reactions_conv_created", "message_reactions", ["conversation_id", "created_at"])
    op.create_index("ix_message_reactions_author_created", "message_reactions", ["author_type", "created_at"])

    op.create_table(
        "user_feedbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.Integer(), server_default="5", nullable=False),
        sa.Column("sentiment", sa.String(length=16), server_default="positive", nullable=False),
        sa.Column("category", sa.String(length=32), server_default="general", nullable=False),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="new", nullable=False),
        sa.Column("admin_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_feedbacks_user_id", "user_feedbacks", ["user_id"])
    op.create_index("ix_user_feedbacks_user_created", "user_feedbacks", ["user_id", "created_at"])
    op.create_index("ix_user_feedbacks_status_created", "user_feedbacks", ["status", "created_at"])

    op.create_table(
        "model_pricing",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_pattern", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("input_usd_per_1m", sa.Float(), server_default="0", nullable=False),
        sa.Column("output_usd_per_1m", sa.Float(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_pattern"),
    )
    op.create_index("ix_model_pricing_model_pattern", "model_pricing", ["model_pattern"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_model_pricing_model_pattern", table_name="model_pricing")
    op.drop_table("model_pricing")

    op.drop_index("ix_user_feedbacks_status_created", table_name="user_feedbacks")
    op.drop_index("ix_user_feedbacks_user_created", table_name="user_feedbacks")
    op.drop_index("ix_user_feedbacks_user_id", table_name="user_feedbacks")
    op.drop_table("user_feedbacks")

    op.drop_index("ix_message_reactions_author_created", table_name="message_reactions")
    op.drop_index("ix_message_reactions_conv_created", table_name="message_reactions")
    op.drop_index("ix_message_reactions_user_id", table_name="message_reactions")
    op.drop_index("ix_message_reactions_conversation_id", table_name="message_reactions")
    op.drop_index("ix_message_reactions_message_id", table_name="message_reactions")
    op.drop_table("message_reactions")

    op.drop_column("run_telemetry", "hitl_denied_count")
    op.drop_column("run_telemetry", "is_regenerated")

    op.drop_index("ix_audit_logs_record_hash", table_name="audit_logs")
    op.drop_index("ix_audit_logs_session_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_risk_created", table_name="audit_logs")
    op.drop_column("audit_logs", "record_hash")
    op.drop_column("audit_logs", "prev_hash")
    op.drop_column("audit_logs", "diff")
    op.drop_column("audit_logs", "risk_score")

    op.drop_column("users", "ai_reactions_enabled")
