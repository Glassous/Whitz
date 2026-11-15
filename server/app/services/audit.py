import logging
import uuid

from fastapi import Request

from app.core.config import get_settings
from app.db.models import AuditLog, User
from app.db.session import SessionLocal

logger = logging.getLogger("whitz.audit")


async def record(
    action: str,
    *,
    actor: User | uuid.UUID | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    outcome: str = "success",
    severity: str = "info",
    request: Request | None = None,
    session_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> None:
    settings = get_settings()
    if not settings.audit_enabled:
        return
    actor_user_id: uuid.UUID | None = None
    if isinstance(actor, User):
        actor_user_id = actor.id
        actor_email = actor_email or actor.email
    elif isinstance(actor, uuid.UUID):
        actor_user_id = actor
    if session_id is None and request is not None:
        candidate = getattr(request.state, "session_id", None)
        if isinstance(candidate, uuid.UUID):
            session_id = candidate

    ip = None
    user_agent = None
    request_id = None
    if request is not None:
        ip = request.client.host if request.client else None
        user_agent = (request.headers.get("user-agent") or "")[:256] or None
        request_id = getattr(request.state, "request_id", None)

    row = AuditLog(
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        outcome=outcome,
        severity=severity,
        ip=ip,
        user_agent=user_agent,
        request_id=request_id,
        session_id=session_id,
        metadata_=metadata,
    )
    try:
        async with SessionLocal() as db:
            db.add(row)
            await db.commit()
    except Exception:
        logger.warning("audit write failed action=%s", action, exc_info=True)
