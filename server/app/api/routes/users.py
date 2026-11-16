from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.api.deps import get_current_user
from app.api.schemas import (
    ChangePasswordRequest,
    CreditStatusOut,
    RedeemRequest,
    UpdatePersonaRequest,
    UpdateProfileRequest,
    UserOut,
)
from app.core.ratelimit import redeem_limiter
from app.core.security import hash_password, verify_password
from app.db.models import RefreshToken, User
from app.db.session import get_db
from app.services import audit, membership, provisioning

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/me/credits", response_model=CreditStatusOut)
async def get_my_credits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await membership.status(db, user)


@router.post("/me/redeem", response_model=CreditStatusOut)
async def redeem_invite_code(
    body: RedeemRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not redeem_limiter.allow(str(user.id)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "尝试过于频繁，请稍后再试")
    try:
        info = await membership.redeem(db, user, body.code)
    except membership.RedeemError as exc:
        await audit.record(
            "membership.redeem_failed",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.detail) from exc
    await audit.record(
        "membership.redeem",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"tier": info["tier"], "expires_at": info["expires_at"]},
    )
    return info


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(body.old_password, user.password_hash):
        await audit.record(
            "user.password_change_failed",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    await audit.record("user.password_change", actor=user, request=request)


@router.put("/me/persona", response_model=UserOut)
async def update_persona(
    body: UpdatePersonaRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    user.persona = body.persona
    await db.commit()
    await db.refresh(user)
    try:
        provisioning.write_persona(user.hermes_profile, user.persona)
    except OSError:
        pass
    return user