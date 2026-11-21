import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import generate_agent_key, hash_password
from app.db.models import User
from app.services import cross_chat_memory

logger = logging.getLogger("whitz.bootstrap")


async def ensure_admin(db: AsyncSession) -> None:
    settings = get_settings()
    email = settings.admin_email.lower()
    if not email:
        return
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none() is not None:
        return
    namespace = f"u{uuid.uuid4().hex}"
    api_key = generate_agent_key()
    admin = User(
        email=email,
        password_hash=hash_password(settings.admin_password),
        display_name="管理员",
        role="admin",
        agent_namespace=namespace,
        agent_api_key=api_key,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    await cross_chat_memory.ensure_main_conversation(db, admin)
    logger.info("已创建初始管理员 %s", email)
