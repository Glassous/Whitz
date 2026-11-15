import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.services import provisioning

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_RESET_ATTEMPTS = 5
RESET_LOCK_MINUTES = 15


async def issue_tokens(db: AsyncSession, user: User) -> TokenResponse:
    settings = get_settings()
    refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    await db.commit()
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=refresh,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
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
    return await issue_tokens(db, user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")
    return await issue_tokens(db, user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    token_hash = hash_refresh_token(body.refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    token = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if token is None or token.revoked_at is not None or token.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效或已过期")
    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已被禁用")
    token.revoked_at = now
    await db.commit()
    return await issue_tokens(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> None:
    token_hash = hash_refresh_token(body.refresh_token)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()


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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密保答案不正确")

    user.password_hash = hash_password(body.new_password)
    user.reset_failed_attempts = 0
    user.reset_locked_until = None
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()