"""email verification auth and remove security questions

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE users SET email_verified_at = COALESCE(created_at, NOW()) WHERE email_verified_at IS NULL"
    )
    op.execute("DROP TABLE IF EXISTS security_questions CASCADE")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS reset_failed_attempts")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS reset_locked_until")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reset_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("reset_locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "security_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.String(200), nullable=False),
        sa.Column("answer_hash", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "position", name="uq_security_question_position"),
    )
    op.create_index("ix_security_questions_user_id", "security_questions", ["user_id"])
    op.drop_column("users", "email_verified_at")
