import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas import (
    AdminCreditAdjust,
    AdminMembershipUpdate,
    InviteCodeCreate,
    InviteCodeOut,
    InviteCodeUpdate,
    InviteRedemptionOut,
)
from app.core.config import get_settings
from app.db.models import InviteCode, InviteRedemption, User
from app.db.session import get_db
from app.services import audit, membership

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.get("/invite-codes")
async def list_invite_codes(
    tier: str | None = Query(default=None, pattern="^(plus|pro)$"),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(InviteCode)
    if tier:
        stmt = stmt.where(InviteCode.tier == tier)
    if is_active is not None:
        stmt = stmt.where(InviteCode.is_active.is_(is_active))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(InviteCode.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "items": [InviteCodeOut.model_validate(row) for row in result.scalars().all()],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


@router.post("/invite-codes", response_model=InviteCodeOut, status_code=status.HTTP_201_CREATED)
async def create_invite_code(
    body: InviteCodeCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InviteCode:
    expires_at = _aware(body.expires_at)
    now = datetime.now(timezone.utc)
    if expires_at is not None and expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "邀请码过期时间必须晚于当前时间")

    code = None
    for _ in range(8):
        candidate = membership.generate_code()
        exists = await db.scalar(select(func.count()).select_from(InviteCode).where(InviteCode.code == candidate))
        if not exists:
            code = candidate
            break
    if code is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "邀请码生成失败，请重试")

    row = InviteCode(
        code=code,
        tier=body.tier,
        duration_days=body.duration_days,
        max_uses=body.max_uses,
        expires_at=expires_at,
        note=(body.note or "").strip() or None,
        created_by=admin.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await audit.record(
        "invite.create",
        actor=admin,
        target_type="invite_code",
        target_id=str(row.id),
        request=request,
        metadata={"tier": row.tier, "duration_days": row.duration_days, "suffix": row.code[-4:]},
    )
    return row


@router.patch("/invite-codes/{code_id}", response_model=InviteCodeOut)
async def update_invite_code(
    code_id: uuid.UUID,
    body: InviteCodeUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InviteCode:
    row = await db.get(InviteCode, code_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "邀请码不存在")
    row.is_active = body.is_active
    await db.commit()
    await db.refresh(row)
    await audit.record(
        "invite.disable" if not body.is_active else "invite.enable",
        actor=admin,
        target_type="invite_code",
        target_id=str(row.id),
        request=request,
        metadata={"suffix": row.code[-4:]},
    )
    return row


@router.get("/invite-codes/{code_id}/redemptions", response_model=list[InviteRedemptionOut])
async def list_invite_code_redemptions(
    code_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[InviteRedemptionOut]:
    code = await db.get(InviteCode, code_id)
    if code is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "邀请码不存在")
    rows = (
        await db.execute(
            select(InviteRedemption, User.email)
            .outerjoin(User, InviteRedemption.user_id == User.id)
            .where(InviteRedemption.code_id == code_id)
            .order_by(InviteRedemption.redeemed_at.desc())
        )
    ).all()
    return [
        InviteRedemptionOut(
            id=redemption.id,
            code_id=redemption.code_id,
            code=code.code,
            user_id=redemption.user_id,
            user_email=user_email,
            tier=redemption.tier,
            duration_days=redemption.duration_days,
            redeemed_at=redemption.redeemed_at,
        )
        for redemption, user_email in rows
    ]


@router.patch("/users/{user_id}/membership")
async def update_membership(
    user_id: uuid.UUID,
    body: AdminMembershipUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    now = datetime.now(timezone.utc)
    old_tier = membership.effective_tier(user, now)
    new_tier = membership.normalize_tier(body.tier)
    expires_at = _aware(body.expires_at)

    if new_tier == membership.FREE:
        user.membership_tier = membership.FREE
        user.membership_expires_at = None
        if old_tier != membership.FREE:
            user.credit_anchor_at = now
    else:
        if expires_at is None:
            if old_tier == new_tier and user.membership_expires_at:
                expires_at = user.membership_expires_at
            else:
                expires_at = now + timedelta(days=get_settings().membership_default_days)
        if expires_at <= now:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "有效期必须晚于当前时间")
        user.membership_tier = new_tier
        user.membership_expires_at = expires_at
        if old_tier != new_tier:
            user.credit_anchor_at = now

    await db.commit()
    await db.refresh(user)
    await audit.record(
        "membership.admin_update",
        actor=admin,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"email": user.email, "from": old_tier, "to": new_tier},
    )
    return await membership.status(db, user)


@router.post("/users/{user_id}/credits")
async def adjust_credits(
    user_id: uuid.UUID,
    body: AdminCreditAdjust,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.credits == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "调整积分不能为 0")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    await membership.adjust(
        db,
        user,
        body.credits,
        actor_id=admin.id,
        note=(body.note or "").strip() or None,
    )
    await audit.record(
        "credits.admin_adjust",
        actor=admin,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"email": user.email, "credits": body.credits},
    )
    return await membership.status(db, user)
