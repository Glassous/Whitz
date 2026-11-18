import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import generate_hermes_key, hash_password
from app.db.models import User
from app.services import provisioning

logger = logging.getLogger("whitz.bootstrap")


async def ensure_admin(db: AsyncSession) -> None:
    settings = get_settings()
    email = settings.admin_email.lower()
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        return
    profile = f"u{uuid.uuid4().hex}"
    api_key = generate_hermes_key()
    admin = User(
        email=email,
        password_hash=hash_password(settings.admin_password),
        display_name="管理员",
        role="admin",
        hermes_profile=profile,
        hermes_api_key=api_key,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    await db.commit()
    try:
        provisioning.provision_profile(profile, api_key)
    except OSError as exc:
        logger.warning("管理员 profile 开通失败: %s", exc)
    logger.info("已创建初始管理员 %s", email)


async def reconcile_profiles(db: AsyncSession) -> None:
    result = await db.execute(select(User))
    for user in result.scalars().all():
        try:
            provisioning.sync_profile_config(
                user.hermes_profile,
                api_key=user.hermes_api_key,
                memory_enabled=bool(user.memory_enabled and user.memory_consented_at),
                memory_require_confirm=bool(user.memory_require_confirm),
            )
            provisioning.set_parked(user.hermes_profile, parked=not user.is_active)
        except OSError as exc:
            logger.warning("同步 profile %s 失败: %s", user.hermes_profile, exc)