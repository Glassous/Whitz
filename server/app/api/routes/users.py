import base64
import binascii
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    UpdateAiPostsRequest,
    UpdateAiReactionsRequest,
    UpdateAssistantRequest,
    UpdatePersonaRequest,
    UpdateProfileRequest,
    UserCreditLedgerItemOut,
    UserFeedbackCreateRequest,
    UserFeedbackOut,
    UserOut,
    UserSessionOut,
)
from app.core.config import get_settings
from app.core.ratelimit import redeem_limiter
from app.core.security import (
    hash_password_async,
    verify_password_async,
)
from app.db.models import RefreshToken, User, UserFeedback
from app.db.session import get_db
from app.services import audit, membership, sessions_service

router = APIRouter(prefix="/api/users", tags=["users"])

logger = logging.getLogger("whitz")

_AVATAR_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
_AVATAR_EXT_MAP = {"png": ("png", "image/png"), "jpeg": ("jpg", "image/jpeg"), "webp": ("webp", "image/webp")}
_MAX_AVATAR_BYTES = 1_048_576
_AVATAR_EXTS = ("webp", "png", "jpg")
_AVATAR_MIME = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}

# 解析后的头像目录：生产容器以非 root 运行且 /app-data 可能是 root 所有的卷，
# 此时写入会抛 PermissionError 并变成 500，因此这里探测可写目录并缓存结果。
_avatars_root: Path | None = None
_avatars_root_key: str | None = None


def _ensure_writable_dir(path: Path) -> bool:
    probe = path / f".probe-{uuid.uuid4().hex}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
    except OSError:
        return False
    try:
        probe.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def _reset_avatars_dir_cache() -> None:
    global _avatars_root, _avatars_root_key
    _avatars_root = None
    _avatars_root_key = None


def _avatars_dir() -> Path:
    global _avatars_root, _avatars_root_key
    primary = get_settings().app_data_path / "avatars"
    key = str(primary)
    if _avatars_root is not None and _avatars_root_key == key:
        return _avatars_root
    if _ensure_writable_dir(primary):
        _avatars_root, _avatars_root_key = primary, key
        return primary
    logger.warning("头像目录不可写（%s），临时回退到系统临时目录；容器重建后这些头像会丢失", primary)
    fallback = Path(tempfile.gettempdir()) / "whitz-avatars"
    if not _ensure_writable_dir(fallback):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "头像存储暂不可用，请稍后重试")
    _avatars_root, _avatars_root_key = fallback, key
    return fallback


def _write_avatar(target: Path, raw: bytes) -> None:
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        _reset_avatars_dir_cache()
        logger.exception("头像写入失败: %s", target)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "头像保存失败，请稍后重试") from exc


def _remove_avatar_files(stem_prefix: str, user_id: uuid.UUID) -> None:
    try:
        root = _avatars_dir()
    except HTTPException:
        return
    for ext in _AVATAR_EXTS:
        candidate = root / f"{stem_prefix}{user_id}.{ext}"
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            logger.warning("删除旧头像失败: %s", candidate)


def _remove_user_avatars(user_id: uuid.UUID) -> None:
    _remove_avatar_files("", user_id)


def _remove_assistant_avatars(user_id: uuid.UUID) -> None:
    _remove_avatar_files("assistant_", user_id)


def _avatar_response(prefix: str, user_id: uuid.UUID, missing_detail: str) -> Response:
    root = _avatars_dir()
    for ext in _AVATAR_EXTS:
        candidate = root / f"{prefix}{user_id}.{ext}"
        try:
            if not candidate.is_file():
                continue
            content = candidate.read_bytes()
        except OSError:
            logger.warning("读取头像失败: %s", candidate)
            continue
        return Response(
            content=content,
            media_type=_AVATAR_MIME[ext],
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    raise HTTPException(status.HTTP_404_NOT_FOUND, missing_detail)


def _decode_validated_avatar(data_url: str) -> tuple[str, bytes]:
    match = _AVATAR_DATA_URL_RE.match(data_url.strip())
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
    return ext, raw


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


@router.get("/me/credits/ledger", response_model=list[UserCreditLedgerItemOut])
async def get_my_credit_ledger(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await membership.list_user_ledger(db, user.id, limit=limit, offset=offset)


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
        tz_clean = body.timezone.strip()
        try:
            ZoneInfo(tz_clean)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"无效的时区标识: {tz_clean}") from exc
        user.timezone = tz_clean
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
    if not await verify_password_async(body.old_password, user.password_hash):
        await audit.record(
            "user.password_change_failed",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")
    user.password_hash = await hash_password_async(body.new_password)
    current_sid = getattr(request.state, "session_id", None)
    if current_sid is not None:
        # Preserve the current authenticated device while immediately revoking all other devices.
        await db.commit()
        await sessions_service.revoke_user_sessions(db, user.id, exclude_session_id=current_sid)
    else:
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
    return user


@router.put("/me/avatar", response_model=UserOut)
async def upload_avatar(
    body: AvatarUploadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    ext, raw = _decode_validated_avatar(body.data_url)
    _remove_user_avatars(user.id)
    target = _avatars_dir() / f"{user.id}.{ext}"
    _write_avatar(target, raw)
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


@router.patch("/me/assistant", response_model=UserOut)
async def update_assistant_profile(
    body: UpdateAssistantRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    if "assistant_name" in body.model_fields_set:
        cleaned = (body.assistant_name or "").strip()
        user.assistant_name = cleaned or "Whitz"
    await db.commit()
    await db.refresh(user)
    await audit.record(
        "user.assistant_update",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"assistant_name": user.assistant_name},
    )
    return user


@router.put("/me/assistant/avatar", response_model=UserOut)
async def upload_assistant_avatar(
    body: AvatarUploadRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    ext, raw = _decode_validated_avatar(body.data_url)
    _remove_assistant_avatars(user.id)
    target = _avatars_dir() / f"assistant_{user.id}.{ext}"
    _write_avatar(target, raw)
    user.assistant_avatar_url = f"/api/users/{user.id}/assistant-avatar?v={int(time.time() * 1000)}"
    await db.commit()
    await db.refresh(user)
    await audit.record(
        "user.assistant_avatar_update",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    return user


@router.delete("/me/assistant/avatar", response_model=UserOut)
async def delete_assistant_avatar(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    _remove_assistant_avatars(user.id)
    user.assistant_avatar_url = None
    await db.commit()
    await db.refresh(user)
    await audit.record(
        "user.assistant_avatar_reset",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
    )
    return user


@router.get("/me/sessions", response_model=list[UserSessionOut])
async def list_my_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserSessionOut]:
    current_sid = getattr(request.state, "session_id", None)
    return await sessions_service.list_user_active_sessions(db, user.id, current_session_id=current_sid)


@router.delete("/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    found = await sessions_service.revoke_single_user_session(db, user.id, session_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "登录会话不存在")

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
    current_sid = getattr(request.state, "session_id", None)
    revoked_count = await sessions_service.revoke_user_sessions(
        db,
        user.id,
        exclude_session_id=current_sid if exclude_current else None,
    )

    await audit.record(
        "user.sessions_revoke_all",
        actor=user,
        target_type="user",
        target_id=user.id,
        request=request,
        metadata={"exclude_current": exclude_current, "revoked_sessions": revoked_count},
    )


@router.put("/me/ai-reactions", response_model=UserOut)
async def update_ai_reactions(
    body: UpdateAiReactionsRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    prev = bool(user.ai_reactions_enabled)
    next_val = bool(body.ai_reactions_enabled)
    if prev != next_val:
        user.ai_reactions_enabled = next_val
        await db.commit()
        await db.refresh(user)
        await audit.record(
            "user.ai_reactions_toggle",
            actor=user,
            target_type="user",
            target_id=user.id,
            request=request,
            diff={"before": {"ai_reactions_enabled": prev}, "after": {"ai_reactions_enabled": next_val}},
        )
    return user


@router.put("/me/ai-posts", response_model=UserOut)
async def update_ai_posts(
    body: UpdateAiPostsRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    prev = bool(user.ai_posts_enabled)
    next_val = bool(body.ai_posts_enabled)
    if prev != next_val or (next_val and user.ai_posts_consented_at is None):
        user.ai_posts_enabled = next_val
        if next_val:
            user.ai_posts_consented_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)
        await audit.record(
            "user.ai_posts_toggle",
            actor=user,
            target_type="user",
            target_id=user.id,
            request=request,
            diff={"before": {"ai_posts_enabled": prev}, "after": {"ai_posts_enabled": next_val}},
        )
    return user


@router.get("/me/feedback", response_model=list[UserFeedbackOut])
async def list_my_feedback(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserFeedback]:
    rows = (
        await db.execute(
            select(UserFeedback)
            .where(UserFeedback.user_id == user.id)
            .order_by(UserFeedback.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return list(rows)


@router.post("/me/feedback", response_model=UserFeedbackOut, status_code=status.HTTP_201_CREATED)
async def create_my_feedback(
    body: UserFeedbackCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserFeedback:
    sentiment = "positive" if body.rating >= 4 else ("neutral" if body.rating == 3 else "negative")
    row = UserFeedback(
        user_id=user.id,
        rating=body.rating,
        sentiment=sentiment,
        category=body.category,
        content=body.content.strip(),
        status="new",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await audit.record(
        "user.feedback_submit",
        actor=user,
        target_type="user_feedback",
        target_id=row.id,
        request=request,
        metadata={"rating": row.rating, "category": row.category, "sentiment": row.sentiment},
    )
    return row


@router.get("/{user_id}/avatar")
async def get_avatar(user_id: uuid.UUID) -> Response:
    return _avatar_response("", user_id, "头像不存在")


@router.get("/{user_id}/assistant-avatar")
async def get_assistant_avatar(user_id: uuid.UUID) -> Response:
    return _avatar_response("assistant_", user_id, "助手头像不存在")
