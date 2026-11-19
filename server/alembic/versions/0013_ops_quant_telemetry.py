"""add ops alert, run telemetry, and eval run tables

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_telemetry",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_route", sa.String(length=32), server_default="auto", nullable=False),
        sa.Column("model_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="completed", nullable=False),
        sa.Column("ttft_ms", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("tool_calls_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tool_errors_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tools_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("skills_used", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_run_telemetry_run_id"),
    )
    op.create_index("ix_run_telemetry_run_id", "run_telemetry", ["run_id"], unique=True)
    op.create_index("ix_run_telemetry_user_id", "run_telemetry", ["user_id"])
    op.create_index("ix_run_telemetry_conversation_id", "run_telemetry", ["conversation_id"])
    op.create_index("ix_run_telemetry_created", "run_telemetry", ["created_at"])
    op.create_index("ix_run_telemetry_route_created", "run_telemetry", ["model_route", "created_at"])
    op.create_index("ix_run_telemetry_status_created", "run_telemetry", ["status", "created_at"])
    op.create_index("ix_run_telemetry_user_created", "run_telemetry", ["user_id", "created_at"])

    op.create_table(
        "ops_alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("operator", sa.String(length=8), server_default="gt", nullable=False),
        sa.Column("threshold", sa.Float(), server_default="0", nullable=False),
        sa.Column("window_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), server_default="30", nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="warning", nullable=False),
        sa.Column("webhook_url", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ops_alert_rules_metric_key", "ops_alert_rules", ["metric_key"])

    op.create_table(
        "ops_alert_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="warning", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="firing", nullable=False),
        sa.Column("message", sa.String(length=500), server_default="", nullable=False),
        sa.Column("webhook_status", sa.String(length=40), nullable=True),
        sa.Column("acked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["ops_alert_rules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ops_alert_events_status_created", "ops_alert_events", ["status", "created_at"])
    op.create_index("ix_ops_alert_events_rule_created", "ops_alert_events", ["rule_id", "created_at"])

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=24), server_default="dry-run", nullable=False),
        sa.Column("dataset_name", sa.String(length=120), server_default="default", nullable=False),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pass_rate", sa.Float(), server_default="0", nullable=False),
        sa.Column("category_scores", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("git_sha", sa.String(length=64), nullable=True),
        sa.Column("triggered_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_created", "eval_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_created", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_ops_alert_events_rule_created", table_name="ops_alert_events")
    op.drop_index("ix_ops_alert_events_status_created", table_name="ops_alert_events")
    op.drop_table("ops_alert_events")
    op.drop_index("ix_ops_alert_rules_metric_key", table_name="ops_alert_rules")
    op.drop_table("ops_alert_rules")
    op.drop_index("ix_run_telemetry_user_created", table_name="run_telemetry")
    op.drop_index("ix_run_telemetry_status_created", table_name="run_telemetry")
    op.drop_index("ix_run_telemetry_route_created", table_name="run_telemetry")
    op.drop_index("ix_run_telemetry_created", table_name="run_telemetry")
    op.drop_index("ix_run_telemetry_conversation_id", table_name="run_telemetry")
    op.drop_index("ix_run_telemetry_user_id", table_name="run_telemetry")
    op.drop_index("ix_run_telemetry_run_id", table_name="run_telemetry")
    op.drop_table("run_telemetry")
