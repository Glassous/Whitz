from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.api.deps import get_current_user
from app.api.schemas import (
    ChangePasswordRequest,
    UpdatePersonaRequest,
    UpdateProfileRequest,
    UpdateSecurityQuestionsRequest,
    UserOut,
)
from app.core.security import hash_answer, hash_password, verify_password
from app.db.models import RefreshToken, SecurityQuestion, User
from app.db.session import get_db
from app.services import provisioning

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)) -> User:
    return user


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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")
    user.password_hash = hash_password(body.new_password)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()


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


@router.put("/me/security-questions", status_code=status.HTTP_204_NO_CONTENT)
async def update_security_questions(
    body: UpdateSecurityQuestionsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码不正确")
    for q in list(user.security_questions):
        await db.delete(q)
    await db.flush()
    for position, q in enumerate(body.security_questions):
        db.add(
            SecurityQuestion(
                user_id=user.id,
                question=q.question.strip(),
                answer_hash=hash_answer(q.answer),
                position=position,
            )
        )
    await db.commit()