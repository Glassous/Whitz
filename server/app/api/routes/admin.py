import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas import AdminUserOut, AdminUserUpdate
from app.db.models import AuditLog, RefreshToken, User
from app.db.session import get_db
from app.services import audit, provisioning

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(User)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(pattern), func.lower(User.display_name).like(pattern)))
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if severity:
        stmt = stmt.where(AuditLog.severity == severity)
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