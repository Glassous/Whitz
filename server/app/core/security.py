import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings
from app.core.redis import get_redis

_hasher = PasswordHasher()


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    token_version: int | None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(
    user_id: uuid.UUID,
    session_id: uuid.UUID | None = None,
    token_version: int = 0,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "type": "access",
        "ver": token_version,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_claims(token: str) -> AccessClaims | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
    session_id: uuid.UUID | None = None
    raw_sid = payload.get("sid")
    if isinstance(raw_sid, str):
        try:
            session_id = uuid.UUID(raw_sid)
        except ValueError:
            session_id = None
    raw_ver = payload.get("ver")
    token_version = raw_ver if isinstance(raw_ver, int) else None
    return AccessClaims(user_id=user_id, session_id=session_id, token_version=token_version)


def decode_access_token(token: str) -> uuid.UUID | None:
    claims = decode_access_claims(token)
    return claims.user_id if claims else None


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_agent_key() -> str:
    return secrets.token_hex(32)


def session_revoked_key(session_id: uuid.UUID | str) -> str:
    return f"session_revoked:{session_id}"


async def revoke_session(session_id: uuid.UUID | str) -> None:
    settings = get_settings()
    ttl = max(60, int(settings.jwt_access_ttl_minutes) * 60 + 60)
    await get_redis().set(session_revoked_key(session_id), "1", ex=ttl)


async def is_session_revoked(session_id: uuid.UUID | str) -> bool:
    return bool(await get_redis().exists(session_revoked_key(session_id)))