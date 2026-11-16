import uuid
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageDaily


def utc_day():
    return datetime.now(timezone.utc).date()


def tokens_from_usage(usage) -> int:
    if not isinstance(usage, dict):
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, (int, float)):
        return max(0, int(total))
    for first, second in (
        ("prompt_tokens", "completion_tokens"),
        ("input_tokens", "output_tokens"),
    ):
        values = [usage.get(key) for key in (first, second)]
        if any(isinstance(v, (int, float)) for v in values):
            return max(0, sum(int(v) for v in values if isinstance(v, (int, float))))
    return 0


async def record_message(db: AsyncSession, user_id: uuid.UUID) -> None:
    stmt = (
        insert(UsageDaily)
        .values(id=uuid.uuid4(), user_id=user_id, day=utc_day(), messages=1, tokens=0, runs=1)
        .on_conflict_do_update(
            index_elements=[UsageDaily.user_id, UsageDaily.day],
            set_={
                "messages": UsageDaily.messages + 1,
                "runs": UsageDaily.runs + 1,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    )
    await db.execute(stmt)
    await db.commit()


async def record_tokens(db: AsyncSession, user_id: uuid.UUID, tokens: int) -> None:
    if tokens <= 0:
        return
    stmt = (
        insert(UsageDaily)
        .values(id=uuid.uuid4(), user_id=user_id, day=utc_day(), messages=0, tokens=tokens, runs=0)
        .on_conflict_do_update(
            index_elements=[UsageDaily.user_id, UsageDaily.day],
            set_={"tokens": UsageDaily.tokens + tokens, "updated_at": datetime.now(timezone.utc)},
        )
    )
    await db.execute(stmt)
    await db.commit()
