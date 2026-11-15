import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SecurityQuestionOut,
    TokenResponse,
    UserOut,
)
from app.core.config import get_settings
from app.core.ratelimit import reset_password_limiter, security_questions_limiter
from app.core.security import (
    create_access_token,
    generate_hermes_key,
    generate_refresh_token,
    hash_answer,
    hash_password,
    hash_refresh_token,
    verify_answer,
    verify_password,
)
from app.db.models import RefreshToken, SecurityQuestion, User
from app.db.session import get_db
from app.services import audit, provisioning

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_RESET_ATTEMPTS = 5
RESET_LOCK_MINUTES = 15


async def issue_tokens(
    db: AsyncSession,
    user: User,
    request: Request,
    response: Response,
    *,
    session_id: uuid.UUID | None = None,
    family_id: uuid.UUID | None = None,
) -> TokenResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    session_id = session_id or uuid.uuid4()
    family_id = family_id or session_id
    refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            session_id=session_id,
            family_id=family_id,
            user_agent=_user_agent(request),
            client_ip=_client_ip(request),
            last_used_at=now,
            expires_at=now + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    await db.commit()
    _set_refresh_cookie(response, refresh)
    return TokenResponse(
        access_token=create_access_token(user.id, session_id, user.token_version or 0),
        refresh_token=refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
        refresh_expires_in=settings.jwt_refresh_ttl_days * 86400,
        user=UserOut.model_validate(user),
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:256] if ua else None


def _set_refresh_cookie(response: Response, refresh: str) -> None:
    settings = get_settings()
    if not settings.auth_cookie_enabled:
        return
    response.set_cookie(
        settings.auth_cookie_name,
        refresh,
        max_age=settings.jwt_refresh_ttl_days * 86400,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,  # type: ignore[arg-type]
        path=settings.auth_cookie_path,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    if not settings.auth_cookie_enabled:
        return
    response.delete_cookie(settings.auth_cookie_name, path=settings.auth_cookie_path)


def _submitted_refresh(body: RefreshRequest, request: Request) -> str | None:
    return body.refresh_token or request.cookies.get(get_settings().auth_cookie_name)


async def _revoke_family(db: AsyncSession, token: RefreshToken, now: datetime) -> None:
    if token.family_id is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    elif token.revoked_at is None:
        token.revoked_at = now
    await db.commit()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    email = body.email.lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")

    profile = f"u{uuid.uuid4().hex}"
    api_key = generate_hermes_key()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name.strip(),
        hermes_profile=profile,
        hermes_api_key=api_key,
    )
    for position, q in enumerate(body.security_questions):
        user.security_questions.append(
            SecurityQuestion(question=q.question.strip(), answer_hash=hash_answer(q.answer), position=position)
        )
    db.add(user)
    try:
        provisioning.provision_profile(profile, api_key)
    except OSError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Agent 存储初始化失败: {exc}")
    await db.commit()
    await db.refresh(user)
    tokens = await issue_tokens(db, user, request, response)
    await audit.record("auth.register", actor=user, request=request, session_id=None)
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        await audit.record(
            "auth.login_failed",
            actor=user.id if user else None,
            actor_email=body.email.lower(),
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误")
    if not user.is_active:
        await audit.record(
            "auth.login_blocked",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")
    tokens = await issue_tokens(db, user, request, response)
    await audit.record("auth.login", actor=user, request=request)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    raw = _submitted_refresh(body, request)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效或已过期")
    token_hash = hash_refresh_token(raw)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
    )
    token = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if token is None or token.expires_at < now:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效或已过期")
    if token.revoked_at is not None:
        settings = get_settings()
        within_grace = (
            token.rotated_at is not None
            and (now - token.rotated_at).total_seconds() <= settings.auth_refresh_grace_seconds
        )
        if not within_grace:
            await _revoke_family(db, token, now)
        await audit.record(
            "auth.refresh_reuse",
            actor=token.user_id,
            outcome="failure",
            severity="warning",
            request=request,
            metadata={"within_grace": within_grace},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效或已过期")
    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已被禁用")

    settings = get_settings()
    session_id = token.session_id or token.id
    family_id = token.family_id or token.id
    new_refresh = generate_refresh_token()
    token.revoked_at = now
    token.rotated_at = now
    token.last_used_at = now
    token.replaced_by_hash = hash_refresh_token(new_refresh)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(new_refresh),
            session_id=session_id,
            family_id=family_id,
            user_agent=_user_agent(request),
            client_ip=_client_ip(request),
            last_used_at=now,
            expires_at=now + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    await db.commit()
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=create_access_token(user.id, session_id, user.token_version or 0),
        refresh_token=new_refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
        refresh_expires_in=settings.jwt_refresh_ttl_days * 86400,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    raw = _submitted_refresh(body, request)
    now = datetime.now(timezone.utc)
    if raw:
        result = await db.execute(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(raw))
            .with_for_update()
        )
        token = result.scalar_one_or_none()
        if token is not None:
            await _revoke_family(db, token, now)
            await audit.record("auth.logout", actor=token.user_id, request=request)
    _clear_refresh_cookie(response)


@router.get("/security-questions", response_model=list[SecurityQuestionOut])
async def get_security_questions(
    email: str, request: Request, db: AsyncSession = Depends(get_db)
) -> list[SecurityQuestionOut]:
    client_ip = request.client.host if request.client else "unknown"
    if not security_questions_limiter.allow(f"{client_ip}:{email.lower()}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")
    result = await db.execute(
        select(User).where(User.email == email.lower()).options(selectinload(User.security_questions))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")
    return [SecurityQuestionOut(position=q.position, question=q.question) for q in user.security_questions]


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not reset_password_limiter.allow(f"{client_ip}:{body.email.lower()}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")
    result = await db.execute(
        select(User).where(User.email == body.email.lower()).options(selectinload(User.security_questions))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")

    now = datetime.now(timezone.utc)
    if user.reset_locked_until is not None and user.reset_locked_until > now:
        await audit.record(
            "auth.reset_locked",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "失败次数过多，账号已临时锁定，请稍后再试")

    questions = sorted(user.security_questions, key=lambda q: q.position)
    answers_ok = len(questions) == len(body.answers) and all(
        verify_answer(answer, q.answer_hash) for answer, q in zip(body.answers, questions)
    )
    if not answers_ok:
        user.reset_failed_attempts += 1
        if user.reset_failed_attempts >= MAX_RESET_ATTEMPTS:
            user.reset_locked_until = now + timedelta(minutes=RESET_LOCK_MINUTES)
            user.reset_failed_attempts = 0
        await db.commit()
        await audit.record(
            "auth.reset_failed",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密保答案不正确")

    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    user.reset_failed_attempts = 0
    user.reset_locked_until = None
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    await audit.record("auth.password_reset", actor=user, request=request)