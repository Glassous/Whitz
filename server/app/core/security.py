import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

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


def normalize_answer(answer: str) -> str:
    return re.sub(r"\s+", " ", answer.strip().lower())


def hash_answer(answer: str) -> str:
    return _hasher.hash(normalize_answer(answer))


def verify_answer(answer: str, answer_hash: str) -> bool:
    try:
        return _hasher.verify(answer_hash, normalize_answer(answer))
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


def generate_hermes_key() -> str:
    return secrets.token_hex(32)