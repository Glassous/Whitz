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

_SHARED_CLIENT: httpx.AsyncClient | None = None


def _get_shared_client() -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        settings = get_settings()
        _SHARED_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.desktop_llm_request_timeout_seconds, connect=15.0),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
            trust_env=False,
        )
    return _SHARED_CLIENT


async def aclose_shared_client() -> None:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is not None and not _SHARED_CLIENT.is_closed:
        await _SHARED_CLIENT.aclose()
    _SHARED_CLIENT = None


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
    """Model name exposed to desktop clients."""
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
    """Return a shared pooled HTTP client (kept as helper for test monkeypatching)."""
    return _get_shared_client()


def _parse_sse_data_line(line: bytes) -> tuple[int, int]:
    """Parse one complete SSE line; return ``(usage_tokens, delta_output_chars)``."""
    stripped = line.strip()
    if not stripped.startswith(b"data:"):
        return 0, 0
    raw = stripped[5:].strip()
    if not raw or raw == b"[DONE]":
        return 0, 0
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0, 0
    if not isinstance(parsed, dict):
        return 0, 0

    tok = 0
    if isinstance(parsed.get("usage"), dict):
        tok = usage.tokens_from_usage(parsed["usage"])

    chars = 0
    choices = parsed.get("choices")
    if isinstance(choices, list):
        for ch in choices:
            if not isinstance(ch, dict):
                continue
            delta = ch.get("delta") if isinstance(ch.get("delta"), dict) else {}
            for key in ("content", "reasoning_content", "reasoning"):
                val = delta.get(key)
                if isinstance(val, str):
                    chars += len(val)
            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    fn = tc.get("function") if isinstance(tc, dict) and isinstance(tc.get("function"), dict) else {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        chars += len(args)
    return tok, chars


async def proxy_non_stream(user: User, body: dict) -> dict:
    payload = sanitize_body(body)
    started = time.monotonic()
    http = client()
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
    upstream_ok = False
    line_buf = b""
    try:
        http = client()
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
            upstream_ok = True
            async for chunk in resp.aiter_bytes():
                yield chunk
                line_buf += chunk
                while b"\n" in line_buf:
                    line, line_buf = line_buf.split(b"\n", 1)
                    tok, ch = _parse_sse_data_line(line)
                    if tok > 0:
                        tokens = max(tokens, tok)
                    output_chars += ch
            if line_buf.strip():
                tok, ch = _parse_sse_data_line(line_buf)
                if tok > 0:
                    tokens = max(tokens, tok)
                output_chars += ch
    except httpx.HTTPError as exc:
        logger.warning("desktop llm stream unreachable: %s", exc)
        yield b'data: {"error":{"message":"model_unavailable"}}\n\n'
    finally:
        if upstream_ok:
            billed = tokens or (_estimate_tokens(payload, output_chars) if output_chars > 0 else 0)
            if billed > 0:
                await _settle(user.id, billed)


def _extract_usage(chunk: bytes) -> int:
    """Backward-compatible helper for extracting usage tokens from an SSE byte chunk."""
    best = 0
    for line in chunk.split(b"\n"):
        tok, _ = _parse_sse_data_line(line)
        if tok > best:
            best = tok
    return best
