"""OpenAI-compatible proxy used by the desktop app's built-in model.

Only the server holds the platform LLM key. Desktop clients authenticate with a
per-device key and every request is metered against the same credit ledger as web
chat, so the desktop shares account quota instead of shipping credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import DesktopLlmKey, User
from app.db.session import SessionLocal
from app.services import limits, membership, usage

logger = logging.getLogger("whitz.desktop_llm")

KEY_PREFIX = "whitz-dk-"


def hash_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue_key(db: AsyncSession, user: User, label: str = "desktop") -> str:
    token = KEY_PREFIX + secrets.token_urlsafe(32)
    db.add(DesktopLlmKey(user_id=user.id, token_hash=hash_key(token), label=label[:80]))
    await db.commit()
    return token


async def revoke_keys(db: AsyncSession, user: User) -> None:
    rows = await db.execute(select(DesktopLlmKey).where(DesktopLlmKey.user_id == user.id, DesktopLlmKey.revoked_at.is_(None)))
    now = datetime.now(timezone.utc)
    for row in rows.scalars():
        row.revoked_at = now
    await db.commit()


async def user_for_key(db: AsyncSession, token: str) -> User:
    if not token or not token.startswith(KEY_PREFIX):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的桌面模型凭证")
    row = (
        await db.execute(
            select(DesktopLlmKey).where(
                DesktopLlmKey.token_hash == hash_key(token),
                DesktopLlmKey.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "桌面模型凭证已失效")
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不可用")
    now = datetime.now(timezone.utc)
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 300:
        row.last_used_at = now
        await db.commit()
    return user


def upstream_base() -> str:
    settings = get_settings()
    return (settings.desktop_llm_base_url or settings.llm_base_url or "").rstrip("/")


def model_alias() -> str:
    """Model name exposed to desktop clients (and written into local Hermes config)."""
    return get_settings().desktop_llm_model_alias or get_settings().llm_model


def upstream_model() -> str:
    """Real model name sent to the LLM provider.

    Desktop clients ask for ``model_alias``; the proxy must rewrite it because
    providers reject the public alias.
    """
    settings = get_settings()
    return settings.desktop_llm_upstream_model or settings.llm_model or model_alias()


def _estimate_tokens(payload: Any, output_chars: int = 0) -> int:
    text = json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str) else payload
    return max(0, len(text) // 4 + output_chars // 4)


async def _settle(user_id: uuid.UUID, tokens: int) -> None:
    if tokens <= 0:
        return
    async with SessionLocal() as session:
        await usage.record_tokens(session, user_id, tokens)
        await membership.settle(session, user_id, tokens)


async def preflight(db: AsyncSession, user: User) -> membership.Plan:
    plan = membership.plan_for(membership.effective_tier(user))
    if await membership.credit_exhausted(db, user):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "额度已用尽，请稍后或升级套餐")
    if not await limits.allow_chat(user.id, plan.chat_per_minute):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")
    return plan


def sanitize_body(body: dict) -> dict:
    settings = get_settings()
    payload = dict(body)
    payload["model"] = upstream_model()
    limit = max(1, int(settings.desktop_llm_max_tokens))
    # Newer OpenAI models reject max_tokens; preserve whichever field the client used.
    if "max_completion_tokens" in payload:
        requested = payload.get("max_completion_tokens")
        payload["max_completion_tokens"] = (
            min(int(requested), limit) if isinstance(requested, (int, float)) else limit
        )
        payload.pop("max_tokens", None)
    else:
        requested = payload.get("max_tokens")
        payload["max_tokens"] = min(int(requested), limit) if isinstance(requested, (int, float)) else limit
    return payload


def client() -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.desktop_llm_request_timeout_seconds, connect=15.0),
        trust_env=False,
    )


async def proxy_non_stream(user: User, body: dict) -> dict:
    payload = sanitize_body(body)
    started = time.monotonic()
    async with client() as http:
        try:
            resp = await http.post(
                f"{upstream_base()}/chat/completions",
                headers={"Authorization": f"Bearer {get_settings().llm_api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            logger.warning("desktop llm upstream unreachable: %s", exc)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "模型服务暂不可用") from exc
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, resp.text[:400])
        data = resp.json()
    tokens = usage.tokens_from_usage(data.get("usage")) or _estimate_tokens(payload) + _estimate_tokens(
        data.get("choices") or []
    )
    await _settle(user.id, tokens)
    logger.info("desktop llm done user=%s tokens=%s ms=%s", user.id, tokens, int((time.monotonic() - started) * 1000))
    return data


async def proxy_stream(user: User, body: dict) -> AsyncIterator[bytes]:
    payload = sanitize_body(body)
    payload["stream"] = True
    options = payload.get("stream_options") if isinstance(payload.get("stream_options"), dict) else {}
    payload["stream_options"] = {**options, "include_usage": True}
    tokens = 0
    output_chars = 0
    try:
        async with client() as http:
            async with http.stream(
                "POST",
                f"{upstream_base()}/chat/completions",
                headers={
                    "Authorization": f"Bearer {get_settings().llm_api_key}",
                    "Accept": "text/event-stream",
                    "Accept-Encoding": "identity",
                },
                json=payload,
            ) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "ignore")[:400]
                    raise HTTPException(resp.status_code, detail)
                async for chunk in resp.aiter_bytes():
                    yield chunk
                    output_chars += chunk.count(b"content")
                    if b'"usage"' in chunk:
                        tokens = max(tokens, _extract_usage(chunk))
    except httpx.HTTPError as exc:
        logger.warning("desktop llm stream unreachable: %s", exc)
        yield b'data: {"error":{"message":"model_unavailable"}}\n\n'
    finally:
        await _settle(user.id, tokens or _estimate_tokens(payload) + output_chars)


def _extract_usage(chunk: bytes) -> int:
    for line in chunk.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        raw = line[5:].strip()
        if raw == b"[DONE]":
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("usage"), dict):
            return usage.tokens_from_usage(parsed["usage"])
    return 0
