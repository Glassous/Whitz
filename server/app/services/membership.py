"""Membership tiers, credit windows and invite-code redemption.

Credits are derived from tokens: ``1 credit = tokens_per_credit`` tokens. The
ledger stores signed token amounts (negative for consumption) so balances never
suffer from float rounding, and the per-user window anchor makes weekly and
five-hour quotas roll from the moment a user activated their account instead of
calendar boundaries.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import CreditLedger, InviteCode, InviteRedemption, User

logger = logging.getLogger("whitz.membership")

FREE = "free"
PLUS = "plus"
PRO = "pro"
PAID_TIERS = (PLUS, PRO)
ALL_TIERS = (FREE, PLUS, PRO)

WEEK_PERIOD = timedelta(days=7)
FIVE_HOUR_PERIOD = timedelta(hours=5)

# Unambiguous alphabet: no 0/O/1/I.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True)
class Plan:
    tier: str
    label: str
    weekly_credits: int
    five_hour_credits: int | None
    max_runs_per_user: int
    chat_per_minute: int
    run_max_seconds: int
    max_tool_iterations: int
    summary: str


PLANS: dict[str, Plan] = {
    FREE: Plan(
        tier=FREE,
        label="Free",
        weekly_credits=100,
        five_hour_credits=20,
        max_runs_per_user=1,
        chat_per_minute=10,
        run_max_seconds=600,
        max_tool_iterations=30,
        summary="每周 100 积分，5 小时最多 20 积分",
    ),
    PLUS: Plan(
        tier=PLUS,
        label="Plus",
        weekly_credits=1500,
        five_hour_credits=300,
        max_runs_per_user=1,
        chat_per_minute=20,
        run_max_seconds=900,
        max_tool_iterations=60,
        summary="每周 1500 积分，5 小时最多 300 积分",
    ),
    PRO: Plan(
        tier=PRO,
        label="Pro",
        weekly_credits=25000,
        five_hour_credits=None,
        max_runs_per_user=2,
        chat_per_minute=30,
        run_max_seconds=1200,
        max_tool_iterations=200,
        summary="每周 25000 积分，无 5 小时限制",
    ),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def plan_for(tier: str | None) -> Plan:
    return PLANS.get((tier or FREE).lower(), PLANS[FREE])


def normalize_tier(tier: str | None) -> str:
    value = (tier or "").strip().lower()
    if value not in ALL_TIERS:
        raise ValueError(f"无效会员档位: {tier}")
    return value


def effective_tier(user: User, now: datetime | None = None) -> str:
    """Return the tier actually in force, treating lapsed memberships as Free."""
    tier = (user.membership_tier or FREE).lower()
    if tier not in ALL_TIERS or tier == FREE:
        return FREE
    expires = user.membership_expires_at
    if expires is not None and expires <= (now or utcnow()):
        return FREE
    return tier


def window_bounds(anchor: datetime, period: timedelta, now: datetime) -> tuple[datetime, datetime]:
    """Start of the current rolling window and the next reset moment."""
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now <= anchor:
        return anchor, anchor + period
    elapsed = now - anchor
    index = elapsed // period
    start = anchor + period * index
    return start, start + period


async def _net_tokens(
    db: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime | None = None
) -> int:
    stmt = select(func.coalesce(func.sum(CreditLedger.tokens), 0)).where(
        CreditLedger.user_id == user_id, CreditLedger.created_at >= start
    )
    if end is not None:
        stmt = stmt.where(CreditLedger.created_at < end)
    return int(await db.scalar(stmt) or 0)


def _credits(tokens: int) -> float:
    return round(tokens / get_settings().tokens_per_credit, 1)


def _window_status(plan_limit: int | None, used_credits: float, reset_at: datetime) -> dict:
    if plan_limit is None:
        return {"limit": None, "used": 0.0, "remaining": None, "reset_at": reset_at.isoformat()}
    remaining = round(plan_limit - used_credits, 1)
    return {
        "limit": plan_limit,
        "used": round(max(0.0, used_credits), 1),
        "remaining": remaining,
        "reset_at": reset_at.isoformat(),
    }


async def status(db: AsyncSession, user: User, now: datetime | None = None) -> dict:
    """Full credit status for a user (tier, windows, remaining credits)."""
    now = now or utcnow()
    tier = effective_tier(user, now)
    plan = plan_for(tier)
    anchor = user.credit_anchor_at or user.created_at or now
    week_start, week_reset = window_bounds(anchor, WEEK_PERIOD, now)
    five_start, five_reset = window_bounds(anchor, FIVE_HOUR_PERIOD, now)
    week_tokens = await _net_tokens(db, user.id, week_start)
    five_tokens = await _net_tokens(db, user.id, five_start)
    weekly = _window_status(plan.weekly_credits, _credits(-week_tokens), week_reset)
    five_hour = _window_status(plan.five_hour_credits, _credits(-five_tokens), five_reset)
    candidates = [c for c in (weekly["remaining"], five_hour["remaining"]) if c is not None]
    remaining = round(min(candidates), 1) if candidates else 0.0
    return {
        "tier": tier,
        "tier_label": plan.label,
        "expires_at": user.membership_expires_at.isoformat() if user.membership_expires_at else None,
        "anchor_at": anchor.isoformat(),
        "tokens_per_credit": get_settings().tokens_per_credit,
        "weekly": weekly,
        "five_hour": five_hour,
        "remaining": remaining,
        "overdrawn": remaining < 0,
        "plan": plan_payload(plan),
        "plans": plans_payload(),
    }


def plan_payload(plan: Plan) -> dict:
    return {
        "tier": plan.tier,
        "label": plan.label,
        "weekly_credits": plan.weekly_credits,
        "five_hour_credits": plan.five_hour_credits,
        "max_runs_per_user": plan.max_runs_per_user,
        "chat_per_minute": plan.chat_per_minute,
        "run_max_seconds": plan.run_max_seconds,
        "max_tool_iterations": plan.max_tool_iterations,
        "summary": plan.summary,
    }


def plans_payload() -> list[dict]:
    return [plan_payload(PLANS[tier]) for tier in ALL_TIERS]


async def credit_exhausted(db: AsyncSession, user: User) -> bool:
    info = await status(db, user)
    return info["remaining"] <= 0


async def settle(
    db: AsyncSession,
    user_id: uuid.UUID,
    tokens: int,
    *,
    message_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> bool:
    """Record consumption for a finished run. Idempotent per assistant message."""
    if tokens <= 0:
        logger.warning("run finished without token usage user=%s message=%s", user_id, message_id)
        return False
    user = await db.get(User, user_id)
    tier = effective_tier(user) if user is not None else FREE
    stmt = (
        insert(CreditLedger)
        .values(
            user_id=user_id,
            tokens=-abs(int(tokens)),
            kind="consume",
            tier=tier,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        .on_conflict_do_nothing(index_elements=[CreditLedger.message_id])
    )
    result = await db.execute(stmt)
    await db.commit()
    return bool(result.rowcount)


async def adjust(
    db: AsyncSession,
    user: User,
    credits: int,
    *,
    actor_id: uuid.UUID | None = None,
    note: str | None = None,
) -> None:
    """Grant (positive) or revoke (negative) credits within the current windows."""
    tokens = int(credits * get_settings().tokens_per_credit)
    db.add(
        CreditLedger(
            user_id=user.id,
            tokens=tokens,
            kind="adjust",
            tier=effective_tier(user),
            actor_user_id=actor_id,
            note=(note or "")[:255] or None,
        )
    )
    await db.commit()


def generate_code() -> str:
    groups = ["".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(4)]
    return "WZ-" + "-".join(groups)


def normalize_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


class RedeemError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def redeem(db: AsyncSession, user: User, raw_code: str) -> dict:
    """Redeem an invite code, upgrading or extending the user's membership."""
    now = utcnow()
    code_text = normalize_code(raw_code)
    if not code_text:
        raise RedeemError("请输入邀请码")
    result = await db.execute(select(InviteCode).where(InviteCode.code == code_text).with_for_update())
    code = result.scalar_one_or_none()
    if code is None:
        raise RedeemError("邀请码不存在")
    if not code.is_active:
        raise RedeemError("邀请码已停用")
    if code.expires_at is not None and code.expires_at <= now:
        raise RedeemError("邀请码已过期")
    if code.used_count >= code.max_uses:
        raise RedeemError("邀请码已被用完")
    already = await db.scalar(
        select(func.count())
        .select_from(InviteRedemption)
        .where(InviteRedemption.code_id == code.id, InviteRedemption.user_id == user.id)
    )
    if already:
        raise RedeemError("你已使用过该邀请码")

    new_tier = normalize_tier(code.tier)
    current = effective_tier(user, now)
    if current in PAID_TIERS and new_tier != current:
        order = {FREE: 0, PLUS: 1, PRO: 2}
        if order[new_tier] < order[current]:
            raise RedeemError("当前会员等级高于该邀请码，无法降级兑换")

    duration = max(1, int(code.duration_days or get_settings().membership_default_days))
    if current == new_tier and user.membership_expires_at is not None and user.membership_expires_at > now:
        # Same tier renewal: extend without resetting the rolling credit windows.
        user.membership_expires_at = user.membership_expires_at + timedelta(days=duration)
    else:
        user.membership_tier = new_tier
        user.membership_expires_at = now + timedelta(days=duration)
        user.credit_anchor_at = now

    code.used_count = (code.used_count or 0) + 1
    db.add(
        InviteRedemption(
            code_id=code.id,
            user_id=user.id,
            tier=new_tier,
            duration_days=duration,
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RedeemError("你已使用过该邀请码") from exc
    await db.refresh(user)
    return await status(db, user)


async def batch_status(db: AsyncSession, users: list[User], now: datetime | None = None) -> dict:
    """Compute credit status for many users with a single ledger scan."""
    now = now or utcnow()
    if not users:
        return {}
    ids = [u.id for u in users]
    windows: dict[uuid.UUID, tuple[datetime, datetime, datetime, datetime]] = {}
    earliest: datetime | None = None
    for user in users:
        anchor = user.credit_anchor_at or user.created_at or now
        week_start, week_reset = window_bounds(anchor, WEEK_PERIOD, now)
        five_start, five_reset = window_bounds(anchor, FIVE_HOUR_PERIOD, now)
        windows[user.id] = (week_start, week_reset, five_start, five_reset)
        for start in (week_start, five_start):
            earliest = start if earliest is None else min(earliest, start)

    rows = await db.execute(
        select(CreditLedger.user_id, CreditLedger.created_at, CreditLedger.tokens).where(
            CreditLedger.user_id.in_(ids), CreditLedger.created_at >= earliest
        )
    )
    by_user: dict[uuid.UUID, list[tuple[datetime, int]]] = {uid: [] for uid in ids}
    for user_id, created_at, tokens in rows:
        by_user.setdefault(user_id, []).append((created_at, int(tokens)))

    tpc = get_settings().tokens_per_credit
    output: dict[uuid.UUID, dict] = {}
    for user in users:
        tier = effective_tier(user, now)
        plan = plan_for(tier)
        week_start, week_reset, five_start, five_reset = windows[user.id]
        entries = by_user.get(user.id, [])
        week_tokens = sum(t for ts, t in entries if ts >= week_start)
        five_tokens = sum(t for ts, t in entries if ts >= five_start)
        weekly = _window_status(plan.weekly_credits, round(-week_tokens / tpc, 1), week_reset)
        five_hour = _window_status(plan.five_hour_credits, round(-five_tokens / tpc, 1), five_reset)
        candidates = [c for c in (weekly["remaining"], five_hour["remaining"]) if c is not None]
        remaining = round(min(candidates), 1) if candidates else 0.0
        output[user.id] = {
            "tier": tier,
            "tier_label": plan.label,
            "expires_at": user.membership_expires_at.isoformat() if user.membership_expires_at else None,
            "remaining": remaining,
            "weekly_used": weekly["used"],
            "weekly_limit": weekly["limit"],
            "five_hour_used": five_hour["used"],
            "five_hour_limit": five_hour["limit"],
            "week_reset_at": week_reset.isoformat(),
            "five_hour_reset_at": five_reset.isoformat(),
            "overdrawn": remaining < 0,
        }
    return output


async def normalize_expired(db: AsyncSession, user: User, now: datetime | None = None) -> bool:
    """Persist a lapsed membership as Free, starting a fresh credit cycle."""
    now = now or utcnow()
    tier = (user.membership_tier or FREE).lower()
    if tier == FREE:
        return False
    if user.membership_expires_at is not None and user.membership_expires_at <= now:
        user.membership_tier = FREE
        user.membership_expires_at = None
        user.credit_anchor_at = now
        await db.commit()
        return True
    return False
