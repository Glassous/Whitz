import asyncio
import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Date, and_, case, cast, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas import (
    AdminAnalyticsDayOut,
    AdminAnalyticsOut,
    AdminAnalyticsTopUserOut,
    AdminLedgerItemOut,
    AdminUserDetailOut,
    AdminUserOut,
    AdminUserUpdate,
    InviteRedemptionOut,
    UserSessionOut,
)
from app.core.config import Settings, get_settings
from app.core.redis import get_redis
from app.core.security import is_session_revoked, revoke_session
from app.db.models import (
    AuditLog,
    Conversation,
    ConversationFile,
    CreditLedger,
    InviteCode,
    InviteRedemption,
    MemoryCollection,
    MemoryEntry,
    Message,
    RefreshToken,
    UsageDaily,
    User,
)
from app.db.session import detect_pgvector, get_db
from app.services import audit, membership
from app.services.agent_client import AgentClient

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _utc_day_expr(column):
    return cast(func.timezone("UTC", column), Date)


def _smtp_configured(settings: Settings) -> bool:
    host = settings.smtp_host.strip()
    username = settings.smtp_username.strip()
    from_email = settings.smtp_from_email.strip() or username
    if not host or not from_email:
        return False
    if username and not settings.smtp_password:
        return False
    return True


async def _check_agent_health(admin: User) -> dict:
    client = AgentClient(admin.agent_namespace, admin.agent_api_key)
    try:
        info = await asyncio.wait_for(client.health_info(), timeout=2.0)
        return info if isinstance(info, dict) else {"ready": bool(info)}
    except Exception:
        return {"ready": False}
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


async def _normalize_expired_members(db: AsyncSession) -> None:
    """Bulk-demote lapsed memberships before rendering admin views."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(User)
        .where(
            User.membership_tier != membership.FREE,
            User.membership_expires_at.is_not(None),
            User.membership_expires_at <= now,
        )
        .values(membership_tier=membership.FREE, membership_expires_at=None, credit_anchor_at=now)
    )
    if result.rowcount:
        await db.commit()


async def _membership_distribution(db: AsyncSession) -> dict[str, int]:
    await _normalize_expired_members(db)
    tier_rows = await db.execute(select(User.membership_tier, func.count()).group_by(User.membership_tier))
    tiers = {membership.FREE: 0, membership.PLUS: 0, membership.PRO: 0}
    for tier, tier_count in tier_rows:
        key = (tier or membership.FREE).lower()
        if key in tiers:
            tiers[key] = int(tier_count)
    return tiers


async def _build_ledger_items(
    db: AsyncSession, rows: list[CreditLedger], tokens_per_credit: int
) -> list[AdminLedgerItemOut]:
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id is not None}
    actor_map: dict[uuid.UUID, str] = {}
    if actor_ids:
        actor_rows = await db.execute(select(User.id, User.email).where(User.id.in_(actor_ids)))
        actor_map = {uid: email for uid, email in actor_rows}
    tpc = max(1, int(tokens_per_credit))
    return [
        AdminLedgerItemOut(
            id=row.id,
            user_id=row.user_id,
            created_at=row.created_at,
            tokens=int(row.tokens or 0),
            credits=round(int(row.tokens or 0) / tpc, 2),
            kind=row.kind,
            tier=row.tier,
            conversation_id=row.conversation_id,
            message_id=row.message_id,
            actor_user_id=row.actor_user_id,
            actor_email=actor_map.get(row.actor_user_id) if row.actor_user_id else None,
            note=row.note,
        )
        for row in rows
    ]


async def _get_user_active_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_session_id: uuid.UUID | None = None,
) -> list[UserSessionOut]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .order_by(RefreshToken.created_at.asc())
    )
    grouped: dict[uuid.UUID, dict] = {}
    for row in result.scalars().all():
        sid = row.session_id or row.id
        entry = grouped.get(sid)
        last_used = row.last_used_at or row.created_at
        if entry is None:
            grouped[sid] = {
                "session_id": sid,
                "user_agent": row.user_agent,
                "client_ip": row.client_ip,
                "last_used_at": row.last_used_at,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "_sort_last_used": last_used,
            }
            continue
        if row.created_at < entry["created_at"]:
            entry["created_at"] = row.created_at
        if row.expires_at > entry["expires_at"]:
            entry["expires_at"] = row.expires_at
        if last_used >= entry["_sort_last_used"]:
            entry["_sort_last_used"] = last_used
            entry["last_used_at"] = row.last_used_at or entry["last_used_at"]
            entry["user_agent"] = row.user_agent or entry["user_agent"]
            entry["client_ip"] = row.client_ip or entry["client_ip"]

    sessions: list[UserSessionOut] = []
    for sid, entry in sorted(
        grouped.items(),
        key=lambda pair: (pair[1]["_sort_last_used"], pair[1]["created_at"]),
        reverse=True,
    ):
        try:
            if await is_session_revoked(sid):
                continue
        except Exception:
            pass
        sessions.append(
            UserSessionOut(
                session_id=entry["session_id"],
                user_agent=entry["user_agent"],
                client_ip=entry["client_ip"],
                last_used_at=entry["last_used_at"],
                created_at=entry["created_at"],
                expires_at=entry["expires_at"],
                is_current=(current_session_id == sid),
            )
        )
    return sessions


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    since_24h = now - timedelta(hours=24)

    async def count(stmt) -> int:
        value = await db.scalar(select(func.count()).select_from(stmt.subquery()))
        return int(value or 0)

    usage_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageDaily.messages), 0),
                func.coalesce(func.sum(UsageDaily.tokens), 0),
                func.coalesce(func.sum(UsageDaily.runs), 0),
            ).where(UsageDaily.day == today)
        )
    ).one()

    tiers = await _membership_distribution(db)

    consumed = await db.scalar(
        select(func.coalesce(func.sum(CreditLedger.tokens), 0)).where(
            CreditLedger.created_at >= day_start, CreditLedger.kind == "consume"
        )
    )
    settings = get_settings()
    return {
        "users": {
            "total": await count(select(User)),
            "active": await count(select(User).where(User.is_active.is_(True))),
            "admins": await count(select(User).where(User.role == "admin")),
            "new_today": await count(select(User).where(User.created_at >= day_start)),
        },
        "usage_today": {
            "day": today.isoformat(),
            "messages": int(usage_row[0] or 0),
            "tokens": int(usage_row[1] or 0),
            "runs": int(usage_row[2] or 0),
        },
        "conversations": {
            "total": await count(select(Conversation)),
            "active_runs": await count(select(Conversation).where(Conversation.active_run_id.is_not(None))),
        },
        "audit_24h": {
            "failures": await count(
                select(AuditLog).where(AuditLog.created_at >= since_24h, AuditLog.outcome != "success")
            ),
            "critical": await count(
                select(AuditLog).where(AuditLog.created_at >= since_24h, AuditLog.severity == "critical")
            ),
        },
        "membership": tiers,
        "credits_today": {
            "used": round(-int(consumed or 0) / settings.tokens_per_credit, 1),
            "tokens_per_credit": settings.tokens_per_credit,
        },
        "plans": membership.plans_payload(),
        "limits": {
            "max_concurrent_runs": settings.max_concurrent_runs,
            "max_concurrent_runs_per_user": settings.max_concurrent_runs_per_user,
        },
        "generated_at": now.isoformat(),
    }


async def _query_analytics_daily(
    db: AsyncSession,
    start_day,
    end_day,
    days: int,
    tokens_per_credit: int,
) -> tuple[list[AdminAnalyticsDayOut], int, int]:
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    window_end = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    usage_rows = await db.execute(
        select(
            UsageDaily.day,
            func.coalesce(func.sum(UsageDaily.messages), 0),
            func.coalesce(func.sum(UsageDaily.tokens), 0),
            func.coalesce(func.sum(UsageDaily.runs), 0),
            func.count(
                func.distinct(
                    case(
                        (
                            or_(UsageDaily.messages > 0, UsageDaily.tokens > 0, UsageDaily.runs > 0),
                            UsageDaily.user_id,
                        )
                    )
                )
            ),
        )
        .where(UsageDaily.day >= start_day, UsageDaily.day <= end_day)
        .group_by(UsageDaily.day)
    )
    usage_by_day = {
        day: (int(msgs or 0), int(tokens or 0), int(runs or 0), int(active or 0))
        for day, msgs, tokens, runs, active in usage_rows
    }

    user_day_expr = _utc_day_expr(User.created_at)
    new_user_rows = await db.execute(
        select(user_day_expr, func.count(User.id))
        .where(User.created_at >= window_start, User.created_at < window_end)
        .group_by(user_day_expr)
    )
    new_users_by_day = {day: int(cnt or 0) for day, cnt in new_user_rows}

    ledger_day_expr = _utc_day_expr(CreditLedger.created_at)
    credit_rows = await db.execute(
        select(ledger_day_expr, func.coalesce(func.sum(CreditLedger.tokens), 0))
        .where(
            CreditLedger.created_at >= window_start,
            CreditLedger.created_at < window_end,
            CreditLedger.kind == "consume",
        )
        .group_by(ledger_day_expr)
    )
    consumed_by_day = {day: int(tokens or 0) for day, tokens in credit_rows}

    daily: list[AdminAnalyticsDayOut] = []
    total_consumed_tokens = 0
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        msgs, tokens, runs, active = usage_by_day.get(day, (0, 0, 0, 0))
        consumed_tokens = consumed_by_day.get(day, 0)
        total_consumed_tokens += consumed_tokens
        daily.append(
            AdminAnalyticsDayOut(
                day=day.isoformat(),
                messages=msgs,
                tokens=tokens,
                credits=round(-consumed_tokens / tokens_per_credit, 2),
                runs=runs,
                new_users=new_users_by_day.get(day, 0),
                active_users=active,
            )
        )

    window_active_users = int(
        await db.scalar(
            select(func.count(func.distinct(UsageDaily.user_id))).where(
                UsageDaily.day >= start_day,
                UsageDaily.day <= end_day,
                or_(UsageDaily.messages > 0, UsageDaily.tokens > 0, UsageDaily.runs > 0),
            )
        )
        or 0
    )
    return daily, total_consumed_tokens, window_active_users


async def _query_top_users(
    db: AsyncSession,
    start_day,
    end_day,
    tokens_per_credit: int,
) -> list[AdminAnalyticsTopUserOut]:
    window_start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
    window_end = datetime.combine(end_day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    sum_messages = func.coalesce(func.sum(UsageDaily.messages), 0)
    sum_tokens = func.coalesce(func.sum(UsageDaily.tokens), 0)
    sum_runs = func.coalesce(func.sum(UsageDaily.runs), 0)
    top_rows = (
        await db.execute(
            select(
                User.id,
                User.email,
                User.display_name,
                User.membership_tier,
                sum_messages.label("messages"),
                sum_tokens.label("tokens"),
                sum_runs.label("runs"),
            )
            .join(UsageDaily, UsageDaily.user_id == User.id)
            .where(UsageDaily.day >= start_day, UsageDaily.day <= end_day)
            .group_by(User.id, User.email, User.display_name, User.membership_tier)
            .having(or_(sum_tokens > 0, sum_messages > 0, sum_runs > 0))
            .order_by(sum_tokens.desc(), sum_messages.desc(), sum_runs.desc())
            .limit(10)
        )
    ).all()

    top_user_ids = [row.id for row in top_rows]
    top_ledger_tokens: dict[uuid.UUID, int] = {}
    if top_user_ids:
        ledger_user_rows = await db.execute(
            select(CreditLedger.user_id, func.coalesce(func.sum(CreditLedger.tokens), 0))
            .where(
                CreditLedger.user_id.in_(top_user_ids),
                CreditLedger.created_at >= window_start,
                CreditLedger.created_at < window_end,
                CreditLedger.kind == "consume",
            )
            .group_by(CreditLedger.user_id)
        )
        top_ledger_tokens = {uid: int(tokens or 0) for uid, tokens in ledger_user_rows}

    return [
        AdminAnalyticsTopUserOut(
            user_id=row.id,
            email=row.email,
            display_name=row.display_name,
            membership_tier=row.membership_tier,
            messages=int(row.messages or 0),
            tokens=int(row.tokens or 0),
            credits=(
                round(-top_ledger_tokens[row.id] / tokens_per_credit, 2)
                if row.id in top_ledger_tokens
                else round(int(row.tokens or 0) / tokens_per_credit, 2)
            ),
            runs=int(row.runs or 0),
        )
        for row in top_rows
    ]


async def _query_file_stats(db: AsyncSession) -> dict[str, int]:
    file_row = (
        await db.execute(
            select(
                func.count(case((ConversationFile.status == "ready", ConversationFile.id))),
                func.coalesce(
                    func.sum(case((ConversationFile.status == "ready", ConversationFile.size_bytes), else_=0)),
                    0,
                ),
                func.count(
                    case(
                        (
                            and_(ConversationFile.status == "ready", ConversationFile.is_global.is_(True)),
                            ConversationFile.id,
                        )
                    )
                ),
                func.count(
                    case(
                        (
                            and_(ConversationFile.status == "ready", ConversationFile.source == "assistant"),
                            ConversationFile.id,
                        )
                    )
                ),
                func.count(case((ConversationFile.status == "pending", ConversationFile.id))),
            )
        )
    ).one()
    return {
        "total_files": int(file_row[0] or 0),
        "total_bytes": int(file_row[1] or 0),
        "global_files": int(file_row[2] or 0),
        "assistant_files": int(file_row[3] or 0),
        "pending_files": int(file_row[4] or 0),
    }


@router.get("/analytics", response_model=AdminAnalyticsOut)
async def analytics(
    days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
) -> AdminAnalyticsOut:
    now = datetime.now(timezone.utc)
    end_day = now.date()
    start_day = end_day - timedelta(days=days - 1)
    tpc = max(1, int(get_settings().tokens_per_credit))

    membership_distribution = await _membership_distribution(db)
    daily, total_consumed_tokens, window_active_users = await _query_analytics_daily(
        db, start_day, end_day, days, tpc
    )
    top_users = await _query_top_users(db, start_day, end_day, tpc)
    file_stats = await _query_file_stats(db)

    summary = {
        "total_messages": sum(item.messages for item in daily),
        "total_tokens": sum(item.tokens for item in daily),
        "total_credits": round(-total_consumed_tokens / tpc, 2),
        "total_runs": sum(item.runs for item in daily),
        "total_new_users": sum(item.new_users for item in daily),
        "active_users": window_active_users,
    }

    return AdminAnalyticsOut(
        days=days,
        start_day=start_day.isoformat(),
        end_day=end_day.isoformat(),
        tokens_per_credit=tpc,
        daily=daily,
        top_users=top_users,
        membership_distribution=membership_distribution,
        file_stats=file_stats,
        summary=summary,
        generated_at=now,
    )


async def _query_active_runs(
    db: AsyncSession, now: datetime, run_max_seconds: int
) -> list[dict]:
    active_rows = (
        await db.execute(
            select(Conversation, User)
            .join(User, Conversation.user_id == User.id)
            .where(Conversation.active_run_id.is_not(None))
            .order_by(Conversation.last_message_at.asc().nullslast(), Conversation.updated_at.asc())
        )
    ).all()

    active_runs = []
    for conv, owner in active_rows:
        started_ref = _aware(conv.last_message_at or conv.updated_at or conv.created_at)
        duration_seconds = max(0, int((now - started_ref).total_seconds())) if started_ref else 0
        is_stalled = duration_seconds > run_max_seconds or duration_seconds > 600
        active_runs.append(
            {
                "conversation_id": str(conv.id),
                "title": conv.title,
                "user_id": str(owner.id),
                "user_email": owner.email,
                "user_display_name": owner.display_name,
                "active_run_id": conv.active_run_id,
                "active_run_status": conv.active_run_status,
                "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
                "duration_seconds": duration_seconds,
                "is_stalled": is_stalled,
            }
        )
    return active_runs


async def _query_failure_anomalies(
    db: AsyncSession, since_24h: datetime
) -> tuple[list[dict], list[dict], int, list[dict]]:
    spike_rows = (
        await db.execute(
            select(
                AuditLog.action,
                func.count(AuditLog.id).label("cnt"),
                func.max(AuditLog.created_at).label("latest_at"),
            )
            .where(AuditLog.created_at >= since_24h, AuditLog.outcome != "success")
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc(), func.max(AuditLog.created_at).desc())
            .limit(10)
        )
    ).all()
    failure_spikes_24h = [
        {
            "action": row.action,
            "count": int(row.cnt or 0),
            "latest_at": row.latest_at.isoformat() if row.latest_at else None,
        }
        for row in spike_rows
    ]

    actor_rows = (
        await db.execute(
            select(
                AuditLog.actor_email,
                func.count(AuditLog.id).label("cnt"),
                func.max(AuditLog.created_at).label("latest_at"),
            )
            .where(
                AuditLog.created_at >= since_24h,
                AuditLog.outcome != "success",
                AuditLog.actor_email.is_not(None),
                AuditLog.actor_email != "",
            )
            .group_by(AuditLog.actor_email)
            .order_by(func.count(AuditLog.id).desc(), func.max(AuditLog.created_at).desc())
            .limit(10)
        )
    ).all()

    actor_emails = [row.actor_email for row in actor_rows if row.actor_email]
    latest_action_by_actor: dict[str, str] = {}
    if actor_emails:
        latest_rows = await db.execute(
            select(AuditLog.actor_email, AuditLog.action)
            .distinct(AuditLog.actor_email)
            .where(
                AuditLog.created_at >= since_24h,
                AuditLog.outcome != "success",
                AuditLog.actor_email.in_(actor_emails),
            )
            .order_by(AuditLog.actor_email, AuditLog.created_at.desc(), AuditLog.id.desc())
        )
        latest_action_by_actor = {email: action for email, action in latest_rows if email}

    top_failing_actors_24h = [
        {
            "actor_email": row.actor_email,
            "count": int(row.cnt or 0),
            "latest_action": latest_action_by_actor.get(row.actor_email, ""),
        }
        for row in actor_rows
    ]

    failed_messages_24h = int(
        await db.scalar(
            select(func.count(Message.id)).where(
                Message.role == "assistant",
                Message.status == "failed",
                Message.created_at >= since_24h,
            )
        )
        or 0
    )

    failed_rows = (
        await db.execute(
            select(Message, User.email)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(User, Conversation.user_id == User.id)
            .where(Message.role == "assistant", Message.status == "failed")
            .order_by(Message.created_at.desc())
            .limit(20)
        )
    ).all()
    recent_failed_messages = [
        {
            "message_id": str(msg.id),
            "conversation_id": str(msg.conversation_id),
            "user_email": email,
            "status": msg.status,
            "created_at": msg.created_at.isoformat(),
        }
        for msg, email in failed_rows
    ]
    return failure_spikes_24h, top_failing_actors_24h, failed_messages_24h, recent_failed_messages


@router.get("/monitor")
async def monitor(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    settings = get_settings()

    try:
        await db.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        postgres_ok = False

    try:
        redis_ok = bool(await get_redis().ping())
    except Exception:
        redis_ok = False

    agent_info = await _check_agent_health(admin)
    agent_ok = bool(agent_info.get("ready"))
    worker_ok = bool(agent_info.get("redis", agent_ok)) if agent_ok else False
    pgvector_ok = await detect_pgvector(db) if postgres_ok else False
    sandbox_mode = str(agent_info.get("sandbox_mode") or settings.sandbox_mode or "disabled")
    active_runs = await _query_active_runs(db, now, settings.run_max_seconds)
    (
        failure_spikes_24h,
        top_failing_actors_24h,
        failed_messages_24h,
        recent_failed_messages,
    ) = await _query_failure_anomalies(db, since_24h)

    return {
        "services": {
            "postgres": postgres_ok,
            "redis": redis_ok,
            "agent": agent_ok,
            "worker": worker_ok,
            "pgvector": pgvector_ok,
            "sandbox": sandbox_mode != "disabled",
            "sandbox_mode": sandbox_mode,
            "cos_configured": bool(settings.cos_configured),
            "smtp_configured": _smtp_configured(settings),
        },
        "active_runs": active_runs,
        "failure_spikes_24h": failure_spikes_24h,
        "top_failing_actors_24h": top_failing_actors_24h,
        "failed_messages_24h": failed_messages_24h,
        "recent_failed_messages": recent_failed_messages,
        "generated_at": now.isoformat(),
    }


@router.post("/conversations/{conversation_id}/stop")
async def force_stop_run(
    conversation_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    if not conv.active_run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "该会话没有进行中的任务")

    run_id = conv.active_run_id
    owner = await db.get(User, conv.user_id)
    agent_stopped = False
    if owner is not None and owner.agent_namespace and owner.agent_api_key:
        client = AgentClient(owner.agent_namespace, owner.agent_api_key)
        try:
            await asyncio.wait_for(client.cancel_run(run_id), timeout=5.0)
            agent_stopped = True
        except Exception:
            agent_stopped = False
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    await db.execute(
        update(Message)
        .where(
            Message.conversation_id == conv.id,
            Message.role == "assistant",
            Message.status.in_(("streaming", "waiting")),
            or_(Message.run_id == run_id, Message.run_id.is_(None)),
        )
        .values(status="cancelled")
    )
    conv.active_run_id = None
    conv.active_run_status = None
    await db.commit()

    await audit.record(
        "admin.run_force_stop",
        actor=admin,
        target_type="conversation",
        target_id=conv.id,
        request=request,
        metadata={
            "run_id": run_id,
            "user_id": str(conv.user_id),
            "user_email": owner.email if owner else None,
            "agent_stopped": agent_stopped,
        },
    )
    return {
        "conversation_id": str(conv.id),
        "stopped_run_id": run_id,
        "agent_stopped": agent_stopped,
        "status": "cancelled",
    }


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, max_length=200),
    role: str | None = Query(default=None, pattern="^(user|admin)$"),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _normalize_expired_members(db)
    stmt = select(User)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(pattern), func.lower(User.display_name).like(pattern)))
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    users = result.scalars().all()
    summaries = await membership.batch_status(db, list(users))
    items = []
    for user in users:
        payload = AdminUserOut.model_validate(user).model_dump()
        payload["credits"] = summaries.get(user.id)
        items.append(payload)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
async def get_user_detail(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminUserDetailOut:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    await membership.normalize_expired(db, user)
    summaries = await membership.batch_status(db, [user])

    conversation_count = int(
        await db.scalar(select(func.count(Conversation.id)).where(Conversation.user_id == user.id)) or 0
    )
    message_count = int(
        await db.scalar(
            select(func.count(Message.id))
            .select_from(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.user_id == user.id)
        )
        or 0
    )
    file_count = int(
        await db.scalar(
            select(func.count(ConversationFile.id)).where(
                ConversationFile.user_id == user.id,
                ConversationFile.status == "ready",
            )
        )
        or 0
    )
    memory_collection_count = int(
        await db.scalar(select(func.count(MemoryCollection.id)).where(MemoryCollection.user_id == user.id)) or 0
    )
    memory_entry_count = int(
        await db.scalar(select(func.count(MemoryEntry.id)).where(MemoryEntry.user_id == user.id)) or 0
    )
    usage_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageDaily.tokens), 0),
                func.coalesce(func.sum(UsageDaily.messages), 0),
                func.coalesce(func.sum(UsageDaily.runs), 0),
            ).where(UsageDaily.user_id == user.id)
        )
    ).one()

    active_sessions = await _get_user_active_sessions(
        db, user.id, getattr(request.state, "session_id", None)
    )

    ledger_rows = list(
        (
            await db.execute(
                select(CreditLedger)
                .where(CreditLedger.user_id == user.id)
                .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    recent_ledger = await _build_ledger_items(db, ledger_rows, get_settings().tokens_per_credit)

    redemption_rows = (
        await db.execute(
            select(InviteRedemption, InviteCode.code)
            .outerjoin(InviteCode, InviteRedemption.code_id == InviteCode.id)
            .where(InviteRedemption.user_id == user.id)
            .order_by(InviteRedemption.redeemed_at.desc())
        )
    ).all()
    invite_redemptions = [
        InviteRedemptionOut(
            id=row.id,
            code_id=row.code_id,
            code=code,
            user_id=row.user_id,
            user_email=user.email,
            tier=row.tier,
            duration_days=row.duration_days,
            redeemed_at=row.redeemed_at,
        )
        for row, code in redemption_rows
    ]

    payload = AdminUserOut.model_validate(user).model_dump()
    payload.update(
        {
            "credits": summaries.get(user.id),
            "persona": user.persona,
            "email_verified_at": user.email_verified_at,
            "credit_anchor_at": user.credit_anchor_at,
            "updated_at": user.updated_at,
            "profile_context_enabled": user.profile_context_enabled,
            "profile_context_consented_at": user.profile_context_consented_at,
            "memory_enabled": user.memory_enabled,
            "memory_consented_at": user.memory_consented_at,
            "memory_require_confirm": user.memory_require_confirm,
            "memory_collection_count": memory_collection_count,
            "memory_entry_count": memory_entry_count,
            "conversation_count": conversation_count,
            "message_count": message_count,
            "file_count": file_count,
            "total_tokens": int(usage_row[0] or 0),
            "total_messages": int(usage_row[1] or 0),
            "total_runs": int(usage_row[2] or 0),
            "active_sessions": active_sessions,
            "recent_ledger": recent_ledger,
            "invite_redemptions": invite_redemptions,
        }
    )
    return AdminUserDetailOut(**payload)


@router.get("/users/{user_id}/ledger")
async def get_user_ledger(
    user_id: uuid.UUID,
    kind: str | None = Query(default=None, pattern="^(consume|adjust)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    stmt = select(CreditLedger).where(CreditLedger.user_id == user_id)
    if kind:
        stmt = stmt.where(CreditLedger.kind == kind)
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = list(
        (
            await db.execute(
                stmt.order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = await _build_ledger_items(db, rows, get_settings().tokens_per_credit)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/users/{user_id}/sessions", response_model=list[UserSessionOut])
async def get_user_sessions(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[UserSessionOut]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return await _get_user_active_sessions(db, user.id, getattr(request.state, "session_id", None))


@router.delete("/users/{user_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_user_session(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    match_filter = and_(
        RefreshToken.user_id == user.id,
        or_(
            RefreshToken.session_id == session_id,
            and_(RefreshToken.session_id.is_(None), RefreshToken.id == session_id),
        ),
    )
    exists = await db.scalar(select(RefreshToken.id).where(match_filter).limit(1))
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "登录会话不存在")
    now = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken)
        .where(match_filter, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    await revoke_session(session_id)
    await audit.record(
        "admin.session_revoke",
        actor=admin,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"email": user.email, "revoked_session_id": str(session_id)},
    )


def _serialize_audit_row(row: AuditLog, *, mask_pii: bool = False) -> dict:
    email = audit.mask_email(row.actor_email) if mask_pii else row.actor_email
    ip = audit.mask_ip(row.ip) if mask_pii else row.ip
    return {
        "id": row.id,
        "created_at": row.created_at,
        "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
        "actor_email": email,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "outcome": row.outcome,
        "severity": row.severity,
        "risk_score": int(getattr(row, "risk_score", 0) or 0),
        "ip": ip,
        "user_agent": row.user_agent,
        "request_id": row.request_id,
        "session_id": str(row.session_id) if row.session_id else None,
        "metadata": row.metadata_,
        "diff": getattr(row, "diff", None),
        "prev_hash": getattr(row, "prev_hash", None),
        "record_hash": getattr(row, "record_hash", None),
    }


def _apply_audit_filters(
    stmt,
    *,
    q: str | None = None,
    action: str | None = None,
    action_prefix: str | None = None,
    severity: str | None = None,
    outcome: str | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    session_id: uuid.UUID | None = None,
    min_risk: int | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
):
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.startswith(action_prefix.strip()))
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if ip:
        stmt = stmt.where(AuditLog.ip == ip.strip())
    if request_id:
        stmt = stmt.where(AuditLog.request_id == request_id.strip())
    if session_id:
        stmt = stmt.where(AuditLog.session_id == session_id)
    if min_risk is not None and min_risk > 0:
        stmt = stmt.where(AuditLog.risk_score >= min_risk)
    if from_at is not None:
        stmt = stmt.where(AuditLog.created_at >= _aware(from_at))
    if to_at is not None:
        stmt = stmt.where(AuditLog.created_at <= _aware(to_at))
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(AuditLog.actor_email, "")).like(pattern),
                func.lower(AuditLog.action).like(pattern),
                func.lower(func.coalesce(AuditLog.target_id, "")).like(pattern),
                func.lower(func.coalesce(AuditLog.ip, "")).like(pattern),
                func.lower(func.coalesce(AuditLog.request_id, "")).like(pattern),
            )
        )
    return stmt


@router.get("/audit-logs")
async def list_audit_logs(
    q: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=80),
    action_prefix: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, pattern="^(info|warning|critical)$"),
    outcome: str | None = Query(default=None, pattern="^(success|failure)$"),
    ip: str | None = Query(default=None, max_length=64),
    request_id: str | None = Query(default=None, max_length=64),
    session_id: uuid.UUID | None = Query(default=None),
    min_risk: int | None = Query(default=None, ge=0, le=100),
    from_at: datetime | None = Query(default=None),
    to_at: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = _apply_audit_filters(
        select(AuditLog),
        q=q,
        action=action,
        action_prefix=action_prefix,
        severity=severity,
        outcome=outcome,
        ip=ip,
        request_id=request_id,
        session_id=session_id,
        min_risk=min_risk,
        from_at=from_at,
        to_at=to_at,
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [_serialize_audit_row(row) for row in result.scalars().all()]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/audit-logs/verify")
async def verify_audit_chain(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await audit.verify_hash_chain(db, limit=limit)


@router.get("/audit-logs/analytics")
async def audit_analytics(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    end_day = now.date()
    start_day = end_day - timedelta(days=days - 1)
    since = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)

    day_expr = _utc_day_expr(AuditLog.created_at)
    daily_rows = (
        await db.execute(
            select(
                day_expr,
                func.count(AuditLog.id),
                func.coalesce(func.sum(case((AuditLog.outcome != "success", 1), else_=0)), 0),
                func.coalesce(func.sum(case((AuditLog.risk_score >= 60, 1), else_=0)), 0),
            )
            .where(AuditLog.created_at >= since)
            .group_by(day_expr)
            .order_by(day_expr.asc())
        )
    ).all()
    by_day = {r[0]: (int(r[1] or 0), int(r[2] or 0), int(r[3] or 0)) for r in daily_rows}
    daily = [
        {
            "day": (start_day + timedelta(days=i)).isoformat(),
            "total": by_day.get(start_day + timedelta(days=i), (0, 0, 0))[0],
            "failures": by_day.get(start_day + timedelta(days=i), (0, 0, 0))[1],
            "high_risk": by_day.get(start_day + timedelta(days=i), (0, 0, 0))[2],
        }
        for i in range(days)
    ]

    top_actions_rows = (
        await db.execute(
            select(
                AuditLog.action,
                func.count(AuditLog.id),
                func.coalesce(func.sum(case((AuditLog.outcome != "success", 1), else_=0)), 0),
                func.avg(AuditLog.risk_score),
            )
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
            .limit(10)
        )
    ).all()
    top_actions = [
        {
            "action": str(r[0]),
            "count": int(r[1] or 0),
            "failures": int(r[2] or 0),
            "avg_risk": round(float(r[3] or 0.0), 1),
        }
        for r in top_actions_rows
    ]

    top_ip_rows = (
        await db.execute(
            select(
                AuditLog.ip,
                func.count(AuditLog.id),
                func.coalesce(func.sum(case((AuditLog.outcome != "success", 1), else_=0)), 0),
            )
            .where(AuditLog.created_at >= since, AuditLog.ip.is_not(None), AuditLog.ip != "")
            .group_by(AuditLog.ip)
            .order_by(func.sum(case((AuditLog.outcome != "success", 1), else_=0)).desc(), func.count(AuditLog.id).desc())
            .limit(8)
        )
    ).all()
    top_ips = [
        {"ip": str(r[0]), "count": int(r[1] or 0), "failures": int(r[2] or 0)}
        for r in top_ip_rows
    ]

    total_events = sum(d["total"] for d in daily)
    total_failures = sum(d["failures"] for d in daily)
    total_high_risk = sum(d["high_risk"] for d in daily)

    return {
        "window_days": days,
        "summary": {
            "total_events": total_events,
            "failures": total_failures,
            "failure_rate_pct": round((total_failures / max(1, total_events)) * 100, 2) if total_events else 0.0,
            "high_risk_events": total_high_risk,
        },
        "daily": daily,
        "top_actions": top_actions,
        "top_ips": top_ips,
        "generated_at": now.isoformat(),
    }


@router.get("/audit-logs/trace/{trace_id}")
async def trace_audit_timeline(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    cleaned = trace_id.strip()
    if not cleaned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "trace_id_required")
    cond = AuditLog.request_id == cleaned
    try:
        sid = uuid.UUID(cleaned)
        cond = or_(AuditLog.request_id == cleaned, AuditLog.session_id == sid)
    except ValueError:
        pass
    rows = (
        await db.execute(select(AuditLog).where(cond).order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(200))
    ).scalars().all()
    return {
        "trace_id": cleaned,
        "count": len(rows),
        "items": [_serialize_audit_row(r) for r in rows],
    }


@router.get("/audit-logs/export")
async def export_audit_logs(
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|jsonl)$"),
    mask_pii: bool = Query(default=True),
    q: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=80),
    action_prefix: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, pattern="^(info|warning|critical)$"),
    outcome: str | None = Query(default=None, pattern="^(success|failure)$"),
    min_risk: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=2000, ge=1, le=5000),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = _apply_audit_filters(
        select(AuditLog),
        q=q,
        action=action,
        action_prefix=action_prefix,
        severity=severity,
        outcome=outcome,
        min_risk=min_risk,
    )
    rows = (await db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit))).scalars().all()
    serialized = [_serialize_audit_row(r, mask_pii=mask_pii) for r in rows]

    await audit.record(
        "admin.audit_export",
        actor=admin,
        target_type="audit_log",
        severity="warning" if not mask_pii else "info",
        request=request,
        metadata={"format": format, "mask_pii": mask_pii, "exported_count": len(serialized)},
    )

    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if format == "jsonl":
        body = "\n".join(json.dumps(item, ensure_ascii=False, default=str) for item in serialized)
        return Response(
            content=body,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="whitz-audit-{ts_tag}.jsonl"'},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "actor_email",
            "action",
            "target_type",
            "target_id",
            "outcome",
            "severity",
            "risk_score",
            "ip",
            "request_id",
            "session_id",
            "record_hash",
        ]
    )
    for item in serialized:
        writer.writerow(
            [
                item["id"],
                item["created_at"].isoformat() if hasattr(item["created_at"], "isoformat") else item["created_at"],
                item["actor_email"] or "",
                item["action"],
                item["target_type"] or "",
                item["target_id"] or "",
                item["outcome"],
                item["severity"],
                item["risk_score"],
                item["ip"] or "",
                item["request_id"] or "",
                item["session_id"] or "",
                item["record_hash"] or "",
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="whitz-audit-{ts_tag}.csv"'},
    )


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.id == admin.id:
        if body.is_active is False or (body.role is not None and body.role != "admin"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用或降级自己的管理员账号")

    before_state: dict = {}
    after_state: dict = {}
    changes: dict = {}
    if body.is_active is not None and body.is_active != user.is_active:
        before_state["is_active"] = user.is_active
        user.is_active = body.is_active
        after_state["is_active"] = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            user.token_version = (user.token_version or 0) + 1
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
    if body.role is not None and body.role != user.role:
        before_state["role"] = user.role
        user.role = body.role
        after_state["role"] = body.role
        changes["role"] = body.role
    await db.commit()
    await db.refresh(user)
    if changes:
        await audit.record(
            "admin.user_update",
            actor=admin,
            target_type="user",
            target_id=user.id,
            request=request,
            metadata={"changes": changes, "email": user.email},
            diff={"before": before_state, "after": after_state},
        )
    return user