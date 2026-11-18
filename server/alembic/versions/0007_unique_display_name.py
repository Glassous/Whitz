"""enforce case-insensitive unique display_name for username login

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE users SET display_name = BTRIM(display_name) WHERE display_name <> BTRIM(display_name)"
    )
    # Deduplicate any pre-existing case-insensitive collisions before adding the unique index.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                display_name,
                ROW_NUMBER() OVER (PARTITION BY lower(display_name) ORDER BY created_at, id) AS rn
            FROM users
        )
        UPDATE users u
        SET display_name = LEFT(r.display_name, 70) || '_' || r.rn::text || '_' || LEFT(REPLACE(u.id::text, '-', ''), 4)
        FROM ranked r
        WHERE u.id = r.id AND r.rn > 1
        """
    )
    op.create_index(
        "uq_users_display_name_lower",
        "users",
        [sa.text("lower(display_name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_display_name_lower", table_name="users")
