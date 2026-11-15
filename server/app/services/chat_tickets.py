import hashlib
import hmac
import json
import logging
import secrets

from fastapi import HTTPException, Request, status

from app.core.config import get_settings
from app.core.redis import get_redis

logger = logging.getLogger("whitz.tickets")

TICKET_HEADER = "X-Chat-Ticket"
NONCE_HEADER = "X-Chat-Nonce"

ACTION_TTL = {"send": 60, "reconnect": 60, "stop": 30, "approval": 30, "clarify": 30}


def _key(ticket: str) -> str:
    return "chat:ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def issue(user_id, conversation_id, action: str, nonce: str, ip: str | None) -> dict:
    ttl = ACTION_TTL[action]
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"u": str(user_id), "c": str(conversation_id), "a": action, "n": nonce, "ip": ip or ""}
    )
    try:
        await get_redis().set(_key(ticket), payload, ex=ttl)
    except Exception:
        logger.warning("ticket backend unavailable", exc_info=True)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "安全校验服务暂不可用")
    return {"ticket": ticket, "expires_in": ttl}


def _reject(action: str, user_id, reason: str) -> None:
    logger.warning("ticket denied action=%s user=%s reason=%s", action, user_id, reason)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "对话票据无效或已过期")


async def require(request: Request, user_id, conversation_id, action: str) -> None:
    ticket = request.headers.get(TICKET_HEADER)
    nonce = request.headers.get(NONCE_HEADER)
    if not ticket or not nonce:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "缺少对话票据")
    try:
        raw = await get_redis().getdel(_key(ticket))
    except Exception:
        logger.warning("ticket backend unavailable", exc_info=True)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "安全校验服务暂不可用")
    if raw is None:
        _reject(action, user_id, "expired_or_unknown")
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        _reject(action, user_id, "malformed")
    if data.get("u") != str(user_id) or data.get("c") != str(conversation_id) or data.get("a") != action:
        _reject(action, user_id, "binding_mismatch")
    if not hmac.compare_digest(str(data.get("n") or ""), nonce):
        _reject(action, user_id, "nonce_mismatch")
    settings = get_settings()
    if settings.strict_ticket_ip and data.get("ip") and data["ip"] != (client_ip(request) or ""):
        _reject(action, user_id, "ip_mismatch")
