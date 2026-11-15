import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas import AdminUserOut, AdminUserUpdate
from app.core.config import get_settings
from app.db.models import AuditLog, Conversation, RefreshToken, UsageDaily, User
from app.db.session import get_db
from app.services import audit, provisioning

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


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
        "limits": {
            "daily_message_limit": settings.daily_message_limit,
            "daily_token_limit": settings.daily_token_limit,
            "max_concurrent_runs": settings.max_concurrent_runs,
            "max_concurrent_runs_per_user": settings.max_concurrent_runs_per_user,
        },
        "generated_at": now.isoformat(),
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
    return {
        "items": [AdminUserOut.model_validate(u) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/audit-logs")
async def list_audit_logs(
    q: str | None = Query(default=None, max_length=200),
    action: str | None = Query(default=None, max_length=80),
    severity: str | None = Query(default=None, pattern="^(info|warning|critical)$"),
    outcome: str | None = Query(default=None, pattern="^(success|failure)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(AuditLog.actor_email, "")).like(pattern),
                func.lower(AuditLog.action).like(pattern),
                func.lower(func.coalesce(AuditLog.target_id, "")).like(pattern),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        {
            "id": row.id,
            "created_at": row.created_at,
            "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
            "actor_email": row.actor_email,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "outcome": row.outcome,
            "severity": row.severity,
            "ip": row.ip,
            "user_agent": row.user_agent,
            "request_id": row.request_id,
            "session_id": str(row.session_id) if row.session_id else None,
            "metadata": row.metadata_,
        }
        for row in result.scalars().all()
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


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

    changes: dict = {}
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            user.token_version = (user.token_version or 0) + 1
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=datetime.now(timezone.utc))
            )
        try:
            provisioning.set_parked(user.hermes_profile, parked=not body.is_active)
        except OSError:
            pass
    if body.role is not None and body.role != user.role:
        user.role = body.role
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
        )
    return user