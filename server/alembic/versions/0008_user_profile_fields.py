"""add extended user profile fields

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(500), nullable=True))
    op.add_column("users", sa.Column("bio", sa.String(300), nullable=False, server_default=""))
    op.add_column("users", sa.Column("phone", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("location", sa.String(80), nullable=True))
    op.add_column("users", sa.Column("occupation", sa.String(80), nullable=True))
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
    op.drop_column("users", "occupation")
    op.drop_column("users", "location")
    op.drop_column("users", "phone")
    op.drop_column("users", "bio")
    op.drop_column("users", "avatar_url")
