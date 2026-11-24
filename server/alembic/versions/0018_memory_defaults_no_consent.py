"""enable long-term memory by default without requiring user confirmation

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "memory_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "memory_require_confirm",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )
    op.execute("UPDATE users SET memory_enabled = true, memory_require_confirm = false")


def downgrade() -> None:
    op.alter_column(
        "users",
        "memory_require_confirm",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )
    op.alter_column(
        "users",
        "memory_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )
