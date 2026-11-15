import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger("whitz.titles")

SYSTEM_PROMPT = (
    "你是对话标题生成器。根据内容生成一个简洁、具体的中文标题，"
    "不超过 18 个汉字（或 30 个字符）。只输出标题本身，"
    "不要引号、前缀、编号、标点或解释。"
)

AUTO_TEMPLATE = (
    "用户消息：\n{user}\n\n"
    "最终回复：\n{assistant}\n\n"
    "请为这段对话生成一个标题。"
)

USER_MESSAGES_TEMPLATE = (
    "以下是用户在一段对话中发送的消息：\n{messages}\n\n"
    "请根据这些消息为对话生成一个标题。"
)


class TitleServiceError(Exception):
    pass


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def build_auto_prompt(user_text: str, assistant_text: str) -> str:
    return AUTO_TEMPLATE.format(
        user=_clip(user_text, 800),
        assistant=_clip(assistant_text, 2000),
    )


def build_user_messages_prompt(messages: list[str]) -> str:
    lines: list[str] = []
    used = 0
    for raw in messages:
        text = " ".join((raw or "").split())
        if not text:
            continue
        text = text[:500]
        if used + len(text) > 3000:
            remaining = 3000 - used
            if remaining >= 40:
                lines.append(text[:remaining])
            break
        lines.append(text)
        used += len(text)
    if not lines:
        raise TitleServiceError("没有可用的用户消息")
    numbered = "\n".join(f"{idx}. {text}" for idx, text in enumerate(lines, 1))
    return USER_MESSAGES_TEMPLATE.format(messages=numbered)


def clean_title(raw: str) -> str:
    text = (raw or "").strip()
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    text = first
    for _ in range(2):
        text = text.strip().strip("\"'“”‘’`#* ")
    text = text.rstrip("。.!！?？:：;；,，")
    text = " ".join(text.split())
    if len(text) > 40:
        text = text[:40].rstrip()
    return text


def _chat_url() -> str:
    settings = get_settings()
    base = settings.llm_base_url.strip().rstrip("/")
    if not base:
        raise TitleServiceError("标题服务未配置")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.llm_api_key:
        raise TitleServiceError("标题服务未配置")
    return {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }


def _payload(prompt: str, stream: bool) -> dict:
    settings = get_settings()
    if not settings.llm_model:
        raise TitleServiceError("标题服务未配置")
    return {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": stream,
        "temperature": 0.3,
        "max_tokens": 256,
    }


def _content_value(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for part in value:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


async def complete_title(prompt: str) -> str:
    timeout = httpx.Timeout(20.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_chat_url(), headers=_headers(), json=_payload(prompt, False))
        if resp.status_code >= 400:
            raise TitleServiceError(f"标题服务返回 {resp.status_code}")
        data = resp.json()
    choices = data.get("choices") if isinstance(data, dict) else None
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
    content = _content_value((message or {}).get("content"))
    title = clean_title(content)
    if not title:
        raise TitleServiceError("标题服务返回空内容")
    return title


async def stream_title(prompt: str) -> AsyncIterator[str]:
    timeout = httpx.Timeout(30.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", _chat_url(), headers=_headers(), json=_payload(prompt, True)) as resp:
            if resp.status_code >= 400:
                raise TitleServiceError(f"标题服务返回 {resp.status_code}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except (json.JSONDecodeError, ValueError):
                    continue
                for choice in obj.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta") or {}
                    text = _content_value(delta.get("content"))
                    if text:
                        yield text


def _sse(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


async def title_events(prompt: str) -> AsyncIterator[dict]:
    parts: list[str] = []
    try:
        async for delta in stream_title(prompt):
            parts.append(delta)
            yield _sse("title.delta", {"text": delta})
    except TitleServiceError as exc:
        logger.warning("title generation failed: %s", exc)
        yield _sse("error", {"detail": "标题生成失败，请稍后重试"})
        return
    except Exception:
        logger.exception("title generation failed")
        yield _sse("error", {"detail": "标题生成失败，请稍后重试"})
        return
    title = clean_title("".join(parts))
    if not title:
        yield _sse("error", {"detail": "标题生成失败，请稍后重试"})
        return
    yield _sse("title.done", {"title": title})
