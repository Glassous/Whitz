import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    EmailCodeLoginRequest,
    EmailCodeRequest,
    EmailCodeResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
)
from app.core.config import get_settings
from app.core.ratelimit import (
    email_code_addr_limiter,
    email_code_ip_limiter,
    login_code_limiter,
    reset_password_limiter,
)
from app.core.security import (
    create_access_token,
    generate_hermes_key,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db.models import RefreshToken, User
from app.db.session import get_db
from app.services import audit, email as email_service, provisioning

router = APIRouter(prefix="/api/auth", tags=["auth"])


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


@router.post("/email-code", response_model=EmailCodeResponse)
async def send_email_code(
    body: EmailCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EmailCodeResponse:
    email = body.email.strip().lower()
    client_ip = _client_ip(request) or "unknown"
    if not email_code_ip_limiter.allow(client_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")
    if not email_code_addr_limiter.allow(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "该邮箱请求验证码过于频繁，请稍后再试")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if body.purpose == "register":
        if user is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")
    else:
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")

    try:
        sent = await email_service.send_verification_code(body.purpose, email)
    except email_service.EmailCooldownError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except email_service.EmailNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except email_service.EmailDeliveryError as exc:
        await audit.record(
            "auth.email_code_failed",
            actor=user,
            actor_email=email,
            outcome="failure",
            severity="warning",
            request=request,
            metadata={"purpose": body.purpose},
        )
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    await audit.record(
        "auth.email_code_sent",
        actor=user,
        actor_email=email,
        request=request,
        metadata={"purpose": body.purpose},
    )
    return EmailCodeResponse(
        message="验证码已发送，请查收邮箱",
        expires_in=sent.expires_in,
        cooldown=sent.cooldown,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    email = body.email.strip().lower()
    display_name = body.display_name.strip()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")
    existing_name = await db.execute(
        select(User.id).where(func.lower(User.display_name) == display_name.lower())
    )
    if existing_name.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被使用")

    try:
        await email_service.verify_email_code("register", email, body.code, consume=False)
    except email_service.InvalidEmailCodeError as exc:
        await audit.record(
            "auth.register_code_failed",
            actor_email=email,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    profile = f"u{uuid.uuid4().hex}"
    api_key = generate_hermes_key()
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=display_name,
        hermes_profile=profile,
        hermes_api_key=api_key,
        email_verified_at=now,
    )
    db.add(user)
    try:
        provisioning.provision_profile(profile, api_key)
    except OSError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Agent 存储初始化失败: {exc}")
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_users_display_name_lower" in str(exc.orig):
            raise HTTPException(status.HTTP_409_CONFLICT, "该用户名已被使用") from exc
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册") from exc
    await email_service.consume_verification_code("register", email)
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
    ident = body.login_id.lower()
    if "@" in ident:
        result = await db.execute(select(User).where(User.email == ident))
    else:
        result = await db.execute(select(User).where(func.lower(User.display_name) == ident))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        await audit.record(
            "auth.login_failed",
            actor=user.id if user else None,
            actor_email=user.email if user else ident,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号或密码错误")
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


@router.post("/login/code", response_model=TokenResponse)
async def login_with_code(
    body: EmailCodeLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    email = body.email.strip().lower()
    client_ip = _client_ip(request) or "unknown"
    if not login_code_limiter.allow(f"{client_ip}:{email}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        await audit.record(
            "auth.login_failed",
            actor_email=email,
            outcome="failure",
            severity="warning",
            request=request,
            metadata={"method": "email_code"},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "该邮箱未注册")
    if not user.is_active:
        await audit.record(
            "auth.login_blocked",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")

    try:
        await email_service.verify_email_code("login", email, body.code, consume=True)
    except email_service.InvalidEmailCodeError as exc:
        await audit.record(
            "auth.login_failed",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
            metadata={"method": "email_code"},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(user)

    tokens = await issue_tokens(db, user, request, response)
    await audit.record("auth.login", actor=user, request=request, metadata={"method": "email_code"})
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


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    email = body.email.strip().lower()
    client_ip = _client_ip(request) or "unknown"
    if not reset_password_limiter.allow(f"{client_ip}:{email}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")

    try:
        await email_service.verify_email_code("reset_password", email, body.code, consume=True)
    except email_service.InvalidEmailCodeError as exc:
        await audit.record(
            "auth.reset_failed",
            actor=user,
            outcome="failure",
            severity="warning",
            request=request,
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    now = datetime.now(timezone.utc)
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1
    if user.email_verified_at is None:
        user.email_verified_at = now
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()
    await audit.record("auth.password_reset", actor=user, request=request)
