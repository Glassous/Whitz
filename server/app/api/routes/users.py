import base64
import binascii
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    AvatarUploadRequest,
    ChangePasswordRequest,
    CreditStatusOut,
    ProfileContextUpdateRequest,
    RedeemRequest,
    UpdatePersonaRequest,
    UpdateProfileRequest,
    UserOut,
    UserSessionOut,
)
from app.core.config import get_settings
from app.core.ratelimit import redeem_limiter
from app.core.security import (
    hash_password,
    is_session_revoked,
    revoke_session,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.db.session import get_db
from app.services import audit, membership, provisioning

router = APIRouter(prefix="/api/users", tags=["users"])

_AVATAR_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
_AVATAR_EXT_MAP = {"png": ("png", "image/png"), "jpeg": ("jpg", "image/jpeg"), "webp": ("webp", "image/webp")}
_MAX_AVATAR_BYTES = 1_048_576


def _avatars_dir() -> Path:
    path = Path(get_settings().hermes_data_dir) / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_user_avatars(user_id: uuid.UUID) -> None:
    root = _avatars_dir()
    for ext in ("webp", "png", "jpg"):
        candidate = root / f"{user_id}.{ext}"
        if candidate.exists():
            candidate.unlink(missing_ok=True)


def _valid_image_magic(fmt: str, data: bytes) -> bool:
    if fmt == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if fmt == "jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if fmt == "webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


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
    if not await redeem_limiter.allow(str(user.id)):
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
        next_name = body.display_name.strip()
        existing = await db.execute(
            select(User.id).where(func.lower(User.display_name) == next_name.lower(), User.id != user.id)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被使用")
        user.display_name = next_name
    if "avatar_url" in body.model_fields_set:
        user.avatar_url = body.avatar_url
    if "bio" in body.model_fields_set and body.bio is not None:
        user.bio = body.bio
    if "gender" in body.model_fields_set:
        user.gender = body.gender or None
    if "birthday" in body.model_fields_set:
        user.birthday = body.birthday
    if "phone" in body.model_fields_set:
        user.phone = body.phone
    if "location" in body.model_fields_set:
        user.location = body.location or None
    if "occupation" in body.model_fields_set:
        user.occupation = body.occupation or None
    if "website" in body.model_fields_set:
        user.website = body.website
    if "preferred_language" in body.model_fields_set and body.preferred_language:
        user.preferred_language = body.preferred_language
    if "timezone" in body.model_fields_set and body.timezone:
        user.timezone = body.timezone
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被使用") from exc
    await db.refresh(user)
    return user


@router.patch("/me/profile-context", response_model=UserOut)
async def update_profile_context(
    body: ProfileContextUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if body.enabled:
        if not body.consent:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "开启个人资料上下文注入前请先确认授权")
        user.profile_context_enabled = True
        user.profile_context_consented_at = datetime.now(timezone.utc)
    else:
        user.profile_context_enabled = False
    await db.commit()
    await db.refresh(user)
    await audit.record(
        "user.profile_context_update",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"enabled": user.profile_context_enabled},
    )
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


@router.put("/me/avatar", response_model=UserOut)
async def upload_avatar(
    body: AvatarUploadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    match = _AVATAR_DATA_URL_RE.match(body.data_url.strip())
    if not match:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 PNG、JPEG 或 WebP 格式图片")
    fmt, b64 = match.group(1), match.group(2)
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "头像图片数据无效") from exc
    if not raw or len(raw) > _MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "裁切后的头像大小不能超过 1MB")
    if not _valid_image_magic(fmt, raw):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "头像文件内容与格式不匹配")

    ext, _ = _AVATAR_EXT_MAP[fmt]
    _remove_user_avatars(user.id)
    target = _avatars_dir() / f"{user.id}.{ext}"
    target.write_bytes(raw)
    user.avatar_url = f"/api/users/{user.id}/avatar?v={int(time.time() * 1000)}"
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/me/avatar", response_model=UserOut)
async def delete_avatar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    _remove_user_avatars(user.id)
    user.avatar_url = None
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/me/sessions", response_model=list[UserSessionOut])
async def list_my_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserSessionOut]:
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .order_by(RefreshToken.created_at.asc())
        )
    ).scalars().all()

    current_sid = getattr(request.state, "session_id", None)
    grouped: dict[uuid.UUID, dict] = {}
    for row in rows:
        sid = row.session_id or row.family_id or row.id
        last_used = row.last_used_at or row.created_at
        existing = grouped.get(sid)
        if existing is None:
            grouped[sid] = {
                "session_id": sid,
                "user_agent": row.user_agent,
                "client_ip": row.client_ip,
                "last_used_at": last_used,
                "created_at": row.created_at,
                "expires_at": row.expires_at,
                "is_current": current_sid is not None and sid == current_sid,
            }
        else:
            if row.created_at < existing["created_at"]:
                existing["created_at"] = row.created_at
            if row.expires_at > existing["expires_at"]:
                existing["expires_at"] = row.expires_at
            if last_used >= (existing["last_used_at"] or existing["created_at"]):
                existing["last_used_at"] = last_used
                if row.user_agent:
                    existing["user_agent"] = row.user_agent
                if row.client_ip:
                    existing["client_ip"] = row.client_ip

    sessions: list[UserSessionOut] = []
    for sid, item in grouped.items():
        if await is_session_revoked(sid):
            continue
        sessions.append(UserSessionOut(**item))

    sessions.sort(
        key=lambda s: (
            1 if s.is_current else 0,
            s.last_used_at or s.created_at,
            s.created_at,
        ),
        reverse=True,
    )
    return sessions


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    rows = list(
        (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user.id,
                    or_(
                        RefreshToken.session_id == session_id,
                        RefreshToken.family_id == session_id,
                        RefreshToken.id == session_id,
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "登录会话不存在")

    now = datetime.now(timezone.utc)
    revoke_ids: set[uuid.UUID] = {session_id}
    for row in rows:
        if row.revoked_at is None:
            row.revoked_at = now
        if row.session_id is not None:
            revoke_ids.add(row.session_id)
        if row.family_id is not None:
            revoke_ids.add(row.family_id)
    await db.commit()

    for sid in revoke_ids:
        await revoke_session(sid)

    await audit.record(
        "user.session_revoke",
        actor=user,
        target_type="session",
        target_id=session_id,
        request=request,
    )


@router.delete("/me/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_my_sessions(
    request: Request,
    exclude_current: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    now = datetime.now(timezone.utc)
    current_sid = getattr(request.state, "session_id", None)
    rows = list(
        (
            await db.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user.id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > now,
                )
            )
        )
        .scalars()
        .all()
    )

    revoke_ids: set[uuid.UUID] = set()
    revoked_rows = 0
    for row in rows:
        sid = row.session_id or row.family_id or row.id
        if exclude_current and current_sid is not None and sid == current_sid:
            continue
        row.revoked_at = now
        revoked_rows += 1
        revoke_ids.add(sid)
        if row.session_id is not None:
            revoke_ids.add(row.session_id)
        if row.family_id is not None:
            revoke_ids.add(row.family_id)

    if revoked_rows:
        await db.commit()

    for sid in revoke_ids:
        await revoke_session(sid)

    await audit.record(
        "user.sessions_revoke_all",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"exclude_current": exclude_current, "revoked_sessions": len(revoke_ids)},
    )


@router.get("/{user_id}/avatar")
async def get_avatar(user_id: uuid.UUID) -> Response:
    root = _avatars_dir()
    for ext, mime in (("webp", "image/webp"), ("png", "image/png"), ("jpg", "image/jpeg")):
        candidate = root / f"{user_id}.{ext}"
        if candidate.is_file():
            return Response(
                content=candidate.read_bytes(),
                media_type=mime,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
    raise HTTPException(status.HTTP_404_NOT_FOUND, "头像不存在")
