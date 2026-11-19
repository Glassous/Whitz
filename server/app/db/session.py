from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import pgvector_detected, set_pgvector_enabled

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def detect_pgvector(db: AsyncSession | None = None) -> bool:
    cached = pgvector_detected()
    if cached is not None:
        return cached
    try:
        if db is not None:
            res = await db.execute(text("SELECT EXISTS(SELECT 1 FROM pg_type WHERE typname = 'vector')"))
            has_vec = bool(res.scalar())
        else:
            async with SessionLocal() as session:
                res = await session.execute(text("SELECT EXISTS(SELECT 1 FROM pg_type WHERE typname = 'vector')"))
                has_vec = bool(res.scalar())
    except Exception:
        has_vec = False
    set_pgvector_enabled(has_vec)
    return has_vec


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
