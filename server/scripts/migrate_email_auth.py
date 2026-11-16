"""One-time idempotent migration script for switching to email verification auth.

Removes security questions & legacy reset-lockout columns, adds and backfills
``users.email_verified_at``, and advances ``alembic_version`` to ``0005``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_LOCAL_DB_URL = "postgresql+asyncpg://whitz:whitz_dev_password@localhost:5434/whitz"


async def migrate(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ NULL"
                )
            )
            backfilled = await conn.execute(
                text(
                    "UPDATE users SET email_verified_at = COALESCE(created_at, NOW()) "
                    "WHERE email_verified_at IS NULL"
                )
            )
            await conn.execute(text("DROP TABLE IF EXISTS security_questions CASCADE"))
            await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS reset_failed_attempts"))
            await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS reset_locked_until"))

            has_alembic = await conn.scalar(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            )
            if has_alembic:
                current = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
                if current in (None, "0004"):
                    if current is None:
                        await conn.execute(
                            text("INSERT INTO alembic_version (version_num) VALUES ('0005')")
                        )
                    else:
                        await conn.execute(
                            text("UPDATE alembic_version SET version_num = '0005'")
                        )

            total_users = await conn.scalar(text("SELECT COUNT(*) FROM users"))
            sq_exists = await conn.scalar(
                text("SELECT to_regclass('public.security_questions') IS NOT NULL")
            )
            version = (
                await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
                if has_alembic
                else None
            )

        print(
            f"Migration complete: users={total_users}, "
            f"email_verified_at_backfilled={backfilled.rowcount}, "
            f"security_questions_exists={sq_exists}, alembic_version={version}"
        )
    finally:
        await engine.dispose()


def main() -> int:
    # Ensure server/.env isn't required; prefer explicit DATABASE_URL or local docker-compose port.
    server_dir = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(server_dir))
    database_url = os.environ.get("DATABASE_URL") or DEFAULT_LOCAL_DB_URL
    asyncio.run(migrate(database_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
