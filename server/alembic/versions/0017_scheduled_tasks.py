"""add scheduled_tasks, scheduled_task_runs, and scheduled_task_pending_proposals

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_mode", sa.String(length=16), server_default="dedicated", nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("schedule_type", sa.String(length=16), nullable=False),
        sa.Column("schedule_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Shanghai", nullable=False),
        sa.Column("model_route", sa.String(length=16), server_default="auto", nullable=False),
        sa.Column("skill_names", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=24), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("run_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_runs", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=24), server_default="manual", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_tasks_user_id", "scheduled_tasks", ["user_id"])
    op.create_index("ix_scheduled_tasks_conversation_id", "scheduled_tasks", ["conversation_id"])
    op.create_index("ix_scheduled_tasks_enabled", "scheduled_tasks", ["enabled"])
    op.create_index("ix_scheduled_tasks_status", "scheduled_tasks", ["status"])
    op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])
    op.create_index("ix_scheduled_tasks_user_created", "scheduled_tasks", ["user_id", "created_at"])
    op.create_index("ix_scheduled_tasks_due", "scheduled_tasks", ["enabled", "status", "next_run_at"])

    op.create_table(
        "scheduled_task_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("trigger_type", sa.String(length=16), server_default="scheduled", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_task_runs_task_id", "scheduled_task_runs", ["task_id"])
    op.create_index("ix_scheduled_task_runs_user_id", "scheduled_task_runs", ["user_id"])
    op.create_index("ix_scheduled_task_runs_status", "scheduled_task_runs", ["status"])
    op.create_index("ix_scheduled_task_runs_task_started", "scheduled_task_runs", ["task_id", "started_at"])
    op.create_index("ix_scheduled_task_runs_user_started", "scheduled_task_runs", ["user_id", "started_at"])

    op.create_table(
        "scheduled_task_pending_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=24), server_default="create", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedule_pending_user_id", "scheduled_task_pending_proposals", ["user_id"])
    op.create_index("ix_schedule_pending_status", "scheduled_task_pending_proposals", ["status"])
    op.create_index(
        "ix_schedule_pending_user_status",
        "scheduled_task_pending_proposals",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_schedule_pending_user_status", table_name="scheduled_task_pending_proposals")
    op.drop_index("ix_schedule_pending_status", table_name="scheduled_task_pending_proposals")
    op.drop_index("ix_schedule_pending_user_id", table_name="scheduled_task_pending_proposals")
    op.drop_table("scheduled_task_pending_proposals")

    op.drop_index("ix_scheduled_task_runs_user_started", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_task_started", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_status", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_user_id", table_name="scheduled_task_runs")
    op.drop_index("ix_scheduled_task_runs_task_id", table_name="scheduled_task_runs")
    op.drop_table("scheduled_task_runs")

    op.drop_index("ix_scheduled_tasks_due", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_user_created", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_next_run_at", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_status", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_enabled", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_conversation_id", table_name="scheduled_tasks")
    op.drop_index("ix_scheduled_tasks_user_id", table_name="scheduled_tasks")
    op.drop_table("scheduled_tasks")
