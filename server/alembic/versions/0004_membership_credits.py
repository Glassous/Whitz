"""membership tiers, credit ledger and invite codes

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("membership_tier", sa.String(16), nullable=False, server_default="free"),
    )
    op.add_column(
        "users",
        sa.Column("membership_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("credit_anchor_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET credit_anchor_at = created_at WHERE credit_anchor_at IS NULL")
    op.alter_column(
        "users",
        "credit_anchor_at",
        nullable=False,
        server_default=sa.func.now(),
    )

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("kind", sa.String(16), nullable=False, server_default="consume"),
        sa.Column("tier", sa.String(16), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(255), nullable=True),
        sa.UniqueConstraint("message_id", name="uq_credit_ledger_message"),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])
    op.create_index("ix_credit_ledger_user_created", "credit_ledger", ["user_id", "created_at"])
    op.create_index("ix_credit_ledger_created_at", "credit_ledger", ["created_at"])

    op.create_table(
        "invite_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False, server_default="plus"),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_invite_codes_code", "invite_codes", ["code"], unique=True)

    op.create_table(
        "invite_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invite_codes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code_id", "user_id", name="uq_invite_redemption_code_user"),
    )
    op.create_index("ix_invite_redemptions_code_id", "invite_redemptions", ["code_id"])
    op.create_index("ix_invite_redemptions_user_id", "invite_redemptions", ["user_id"])


def downgrade() -> None:
    op.drop_table("invite_redemptions")
    op.drop_table("invite_codes")
    op.drop_table("credit_ledger")
    op.drop_column("users", "credit_anchor_at")
    op.drop_column("users", "membership_expires_at")
    op.drop_column("users", "membership_tier")
