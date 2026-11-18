"""add gender, birthday, website, preferred_language to users

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("gender", sa.String(40), nullable=True))
    op.add_column("users", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("website", sa.String(255), nullable=True))
    op.add_column(
        "users",
        sa.Column("preferred_language", sa.String(16), nullable=False, server_default="zh-CN"),
    )


def downgrade() -> None:
    op.drop_column("users", "preferred_language")
    op.drop_column("users", "website")
    op.drop_column("users", "birthday")
    op.drop_column("users", "gender")
