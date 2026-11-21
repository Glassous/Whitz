from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
import uuid
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.core.config import get_settings

logger = logging.getLogger("whitz.agent.tools")

HITL_TOOL_NAMES = frozenset({"execute_code", "clarify"})
SUBAGENT_TOOL_NAMES = frozenset({"delegate_subtask"})

_VALID_TODO_STATUS = frozenset({"pending", "in_progress", "completed", "cancelled"})


def _cfg(config: RunnableConfig | None) -> dict[str, Any]:
    if not config:
        return {}
    return dict(config.get("configurable") or {})


def _normalize_todo_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "pending").strip().lower()
        if status not in _VALID_TODO_STATUS:
            status = "pending"
        content = str(
            item.get("content") or item.get("title") or item.get("text") or item.get("task") or ""
        ).strip()
        if not content:
            continue
        normalized.append(
            {
                "id": str(item.get("id") or f"step-{idx + 1}"),
                "content": content,
                "status": status,
                "parent": item.get("parent"),
            }
        )
    return normalized


def _is_global_ip(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_global_ip(str(ip.ipv4_mapped))
    return bool(ip.is_global) and not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    )


def _is_public_url(raw_url: str) -> bool:
    try:
        parsed = urlsplit(raw_url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.strip("[]").lower()
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        return _is_global_ip(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
        if not infos:
            return False
        for info in infos:
            if not _is_global_ip(info[4][0]):
                return False
    except OSError:
        return False
    return True


async def _is_public_url_async(raw_url: str) -> bool:
    return await asyncio.to_thread(_is_public_url, raw_url)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _strip_html(html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[ \t\r\f\v]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


@tool
async def rag_search_workspace(
    query: str,
    file_id: str | None = None,
    top_k: int = 8,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """在当前对话工作区和用户的全局共享文件中执行混合检索（向量语义 + 全文检索 + RRF 融合）。

    当用户提问涉及已上传附件、文档内容或全局资料库时优先调用此工具定位相关片段。
    """
    cfg = _cfg(config)
    retriever = cfg.get("hybrid_retriever")
    user_id = str(cfg.get("user_id") or "")
    conversation_id = str(cfg.get("conversation_id") or "")
    if retriever is None or not user_id or not conversation_id:
        return json.dumps({"results": [], "note": "Hybrid RAG retriever not configured."}, ensure_ascii=False)
    chunks = await retriever.search(
        user_id=user_id,
        conversation_id=conversation_id,
        query=query,
        file_id=file_id,
        top_k=max(1, min(int(top_k or 8), 20)),
    )
    return json.dumps({"count": len(chunks), "results": chunks}, ensure_ascii=False)


@tool
async def memory_search(
    query: str,
    limit: int = 8,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """检索用户的长期个性化记忆与偏好（仅在用户开启记忆功能时返回结果）。"""
    cfg = _cfg(config)
    manager = cfg.get("memory_manager")
    if not cfg.get("memory_enabled"):
        return json.dumps({"enabled": False, "results": []}, ensure_ascii=False)
    if manager is None:
        return json.dumps({"enabled": True, "results": []}, ensure_ascii=False)
    items = await manager.search(
        user_id=str(cfg.get("user_id") or ""),
        agent_namespace=str(cfg.get("agent_namespace") or ""),
        query=query,
        memory_enabled=True,
        limit=max(1, min(int(limit or 8), 20)),
    )
    return json.dumps({"enabled": True, "count": len(items), "results": items}, ensure_ascii=False)


@tool
async def memory_propose(
    content: str,
    target: str = "memory",
    action: str = "add",
    old_content: str | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """保存或提议一条长期用户记忆。若用户开启了写入确认，则会进入待确认队列等待用户审批。

    target: 'memory'（事实/偏好/项目背景）或 'user'（用户个人画像摘要）。
    action: 'add' | 'replace' | 'remove'。
    """
    cfg = _cfg(config)
    manager = cfg.get("memory_manager")
    if manager is None:
        return json.dumps({"status": "unavailable", "message": "MemoryManager 未初始化。"}, ensure_ascii=False)
    res = await manager.propose(
        user_id=str(cfg.get("user_id") or ""),
        agent_namespace=str(cfg.get("agent_namespace") or ""),
        conversation_id=str(cfg.get("conversation_id") or "") or None,
        target=target,
        action=action,
        content=content,
        old_content=old_content,
        memory_enabled=bool(cfg.get("memory_enabled")),
        memory_require_confirm=bool(cfg.get("memory_require_confirm", True)),
    )
    return json.dumps(res, ensure_ascii=False)


@tool
async def todo_list(
    items: list[dict[str, Any]],
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """创建或更新当前任务的执行步骤清单（items: [{id, content, status}]）。

    status 可选: pending | in_progress | completed | cancelled。
    """
    normalized = _normalize_todo_items(items)
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer({"type": "plan.updated", "items": normalized})
    except Exception:
        pass
    return json.dumps({"items": normalized}, ensure_ascii=False)


@tool
async def web_search(
    query: str,
    max_results: int = 5,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """在互联网上搜索最新信息、文档或新闻。"""
    settings = get_settings()
    limit = max(1, min(int(max_results or 5), 10))
    api_key = (settings.search_api_key or "").strip()

    if api_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": api_key,
                        "query": query,
                        "max_results": limit,
                        "include_answer": True,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            results = [
                {
                    "title": str(r.get("title") or "")[:200],
                    "url": str(r.get("url") or "")[:500],
                    "snippet": str(r.get("content") or "")[:800],
                }
                for r in (data.get("results") or [])[:limit]
            ]
            return json.dumps(
                {"provider": "tavily", "answer": data.get("answer"), "results": results},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("Tavily web_search failed (%s); falling back", exc)

    # Free fallback via DuckDuckGo Instant Answer API
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            )
            resp.raise_for_status()
            data = resp.json()
        results: list[dict[str, str]] = []
        if data.get("AbstractText"):
            results.append(
                {
                    "title": str(data.get("Heading") or query),
                    "url": str(data.get("AbstractURL") or ""),
                    "snippet": str(data.get("AbstractText") or "")[:800],
                }
            )
        for topic in data.get("RelatedTopics") or []:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": str(topic.get("Text") or "")[:100],
                        "url": str(topic.get("FirstURL") or ""),
                        "snippet": str(topic.get("Text") or "")[:600],
                    }
                )
            if len(results) >= limit:
                break
        return json.dumps({"provider": "duckduckgo", "results": results}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"provider": "none", "results": [], "error": str(exc)}, ensure_ascii=False)


@tool
async def web_extract(
    url: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """抓取并提取指定公开网页的纯文本正文内容。"""
    cleaned = (url or "").strip()
    if not await _is_public_url_async(cleaned):
        return json.dumps({"error": "仅允许抓取合法的公网 HTTP/HTTPS 页面。", "url": cleaned}, ensure_ascii=False)

    settings = get_settings()
    api_key = (settings.search_api_key or "").strip()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
                resp = await client.post(
                    "https://api.tavily.com/extract",
                    json={"api_key": api_key, "urls": [cleaned]},
                )
                resp.raise_for_status()
                data = resp.json()
            results = data.get("results") or []
            if results:
                content = str(results[0].get("raw_content") or results[0].get("content") or "")
                return json.dumps(
                    {"url": cleaned, "content": content[:12000]},
                    ensure_ascii=False,
                )
        except Exception as exc:
            logger.warning("Tavily web_extract failed (%s); falling back to HTTP fetch", exc)

    try:
        max_bytes = 512 * 1024
        chunks: list[bytes] = []
        total = 0
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            headers={"User-Agent": "WhitzAgent/1.0"},
        ) as client:
            async with client.stream("GET", cleaned) as resp:
                resp.raise_for_status()
                async for piece in resp.aiter_bytes(chunk_size=16384):
                    chunks.append(piece)
                    total += len(piece)
                    if total >= max_bytes:
                        break
        raw_html = b"".join(chunks).decode("utf-8", errors="replace")
        text = _strip_html(raw_html)
        return json.dumps({"url": cleaned, "content": text[:12000]}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"url": cleaned, "error": f"网页抓取失败: {exc}"}, ensure_ascii=False)


_ALLOWED_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_MAX_HTTP_RESPONSE_BYTES = 512 * 1024
_MAX_HTTP_BODY_CHARS = 12000


class _SSRFBlockedError(ValueError):
    """Raised when a request or redirect target resolves to a non-public URL."""


async def _ssrf_request_hook(request: httpx.Request) -> None:
    target_url = str(request.url)
    if not await _is_public_url_async(target_url):
        raise _SSRFBlockedError(f"仅允许请求合法的公网 HTTP/HTTPS 地址: {target_url}")


@tool
async def http_request(
    url: str,
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET",
    headers: dict[str, str] | None = None,
    params: dict[str, str | int | float | bool] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    form_data: dict[str, str | int | float | bool] | None = None,
    body: str | None = None,
    cookies: dict[str, str] | None = None,
    basic_auth: str | None = None,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    timeout_seconds: float = 15.0,
) -> str:
    """发送无终端 HTTP/HTTPS 请求（等效 curl 能力），支持自定义 Method、Headers、Query、JSON/表单/文本 Body、Cookie、Basic Auth、重定向与超时控制。

    仅允许访问公网 HTTP/HTTPS 地址（自动拦截内网/回环/元数据地址及重定向 SSRF）。
    """
    cleaned_url = (url or "").strip()
    if not await _is_public_url_async(cleaned_url):
        return json.dumps(
            {"ok": False, "url": cleaned_url, "error": "仅允许请求合法的公网 HTTP/HTTPS 地址。"},
            ensure_ascii=False,
        )

    normalized_method = (method or "GET").strip().upper()
    if normalized_method not in _ALLOWED_HTTP_METHODS:
        return json.dumps(
            {"ok": False, "url": cleaned_url, "error": f"不支持的 HTTP 方法: {normalized_method}"},
            ensure_ascii=False,
        )

    payload_count = sum(1 for item in (json_body, form_data, body) if item is not None)
    if payload_count > 1:
        return json.dumps(
            {
                "ok": False,
                "url": cleaned_url,
                "error": "json_body、form_data 与 body 不能同时传入，请仅保留一种请求体格式。",
            },
            ensure_ascii=False,
        )

    req_headers: dict[str, str] = {}
    if isinstance(headers, dict):
        for k, v in headers.items():
            key = str(k).strip()
            if key:
                req_headers[key] = str(v)
    if not any(k.lower() == "user-agent" for k in req_headers):
        req_headers["User-Agent"] = "WhitzAgent/1.0"

    req_auth: tuple[str, str] | None = None
    if basic_auth is not None:
        raw_auth = str(basic_auth)
        if ":" not in raw_auth:
            return json.dumps(
                {"ok": False, "url": cleaned_url, "error": "basic_auth 格式应为 'username:password'。"},
                ensure_ascii=False,
            )
        user_part, pass_part = raw_auth.split(":", 1)
        req_auth = (user_part, pass_part)

    clamped_timeout = max(1.0, min(float(timeout_seconds or 15.0), 60.0))
    started = time.monotonic()

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(clamped_timeout),
            follow_redirects=bool(follow_redirects),
            max_redirects=5,
            verify=bool(verify_ssl),
            event_hooks={"request": [_ssrf_request_hook]},
        ) as client:
            request_kwargs: dict[str, Any] = {
                "headers": req_headers,
                "params": params,
                "cookies": cookies,
                "auth": req_auth,
            }
            if json_body is not None:
                request_kwargs["json"] = json_body
            elif form_data is not None:
                request_kwargs["data"] = {str(k): str(v) for k, v in form_data.items()}
            elif body is not None:
                request_kwargs["content"] = body.encode("utf-8")

            async with client.stream(normalized_method, cleaned_url, **request_kwargs) as resp:
                chunks: list[bytes] = []
                total_bytes = 0
                truncated_bytes = False
                if normalized_method != "HEAD":
                    async for piece in resp.aiter_bytes(chunk_size=16384):
                        remaining = _MAX_HTTP_RESPONSE_BYTES - total_bytes
                        if remaining <= 0:
                            truncated_bytes = True
                            break
                        if len(piece) > remaining:
                            chunks.append(piece[:remaining])
                            total_bytes += remaining
                            truncated_bytes = True
                            break
                        chunks.append(piece)
                        total_bytes += len(piece)

                elapsed_ms = int((time.monotonic() - started) * 1000)
                raw_text = b"".join(chunks).decode("utf-8", errors="replace") if chunks else ""
                truncated_text = len(raw_text) > _MAX_HTTP_BODY_CHARS
                return json.dumps(
                    {
                        "ok": 200 <= resp.status_code < 400,
                        "status_code": resp.status_code,
                        "reason_phrase": resp.reason_phrase,
                        "http_version": resp.http_version,
                        "url": str(resp.url),
                        "redirect_count": len(resp.history),
                        "elapsed_ms": elapsed_ms,
                        "headers": dict(resp.headers),
                        "cookies": dict(resp.cookies),
                        "bytes_read": total_bytes,
                        "truncated": bool(truncated_bytes or truncated_text),
                        "body": raw_text[:_MAX_HTTP_BODY_CHARS],
                    },
                    ensure_ascii=False,
                )
    except _SSRFBlockedError as exc:
        return json.dumps({"ok": False, "url": cleaned_url, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "url": cleaned_url,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "error": f"HTTP 请求失败: {exc}",
            },
            ensure_ascii=False,
        )


@tool
async def skill_view(
    name: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """查看指定技能的完整 SKILL.md 指导正文与参数说明。"""
    cfg = _cfg(config)
    catalog: dict[str, dict[str, Any]] = cfg.get("skills_catalog") or {}
    target = (name or "").strip()
    if target in catalog:
        entry = catalog[target]
        return json.dumps(
            {
                "name": entry.get("name", target),
                "description": entry.get("description", ""),
                "category": entry.get("category"),
                "content": entry.get("content") or entry.get("instructions") or entry.get("description") or "",
            },
            ensure_ascii=False,
        )

    # Optionally query PostgreSQL user_skills if pool is available
    pool = cfg.get("pool")
    user_id = cfg.get("user_id")
    if pool is not None and user_id and target:
        try:
            user_uuid = uuid.UUID(str(user_id))
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT name, description, category, content
                        FROM user_skills
                        WHERE user_id = %s AND name = %s AND enabled = TRUE
                        LIMIT 1
                        """,
                        (user_uuid, target),
                    )
                    row = await cur.fetchone()
            if row:
                return json.dumps(
                    {
                        "name": row[0],
                        "description": row[1],
                        "category": row[2],
                        "content": row[3],
                    },
                    ensure_ascii=False,
                )
        except Exception:
            pass

    return json.dumps({"error": f"未找到已启用的技能: {target}"}, ensure_ascii=False)


@tool
async def clarify(
    question: str,
    options: list[str] | None = None,
) -> str:
    """当需求存在关键歧义、缺少必要参数或需要用户做重要取舍时，暂停执行并向用户发起澄清追问。"""
    # Handled inside hitl_gate node via LangGraph interrupt().
    return json.dumps({"question": question, "options": options or []}, ensure_ascii=False)


@tool
async def execute_code(
    code: str,
    language: str = "python",
    reason: str = "",
) -> str:
    """在隔离沙箱中执行 Python / Shell / Node.js 代码以完成计算、数据处理或验证。

    注意：执行前会强制暂停并请求用户确认审批（HITL）。
    """
    # Handled inside hitl_gate node via LangGraph interrupt() + SandboxExecutor.
    return json.dumps({"language": language, "code": code, "reason": reason}, ensure_ascii=False)


@tool
async def request_deep_thinking(
    reason: str,
) -> str:
    """当你判断当前任务存在多步复杂推演、矛盾信息核查、复杂代码分析或疑难规划，且当前尚未开启深度思考模式时，调用此工具立即升档开启深度思考模式并在下一轮深入推理。"""
    return json.dumps(
        {"thinking_enabled": True, "reason": str(reason or "").strip() or "需要更深入的多步推理"},
        ensure_ascii=False,
    )


@tool
async def delegate_subtask(
    role: str,
    task: str,
    context: str = "",
) -> str:
    """将复杂子任务委派给专用子智能体（role='researcher' 深度检索汇总，或 role='coder' 分析与代码设计）。"""
    # Handled inside subagent node invoking Researcher / Coder subgraph.
    return json.dumps({"role": role, "task": task, "context": context}, ensure_ascii=False)


@tool
async def search_chat_history(
    query: str,
    scope: str = "all",
    limit: int = 8,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """检索用户全部旁聊与历史主聊天记录（摘要 + 原始消息全文），用于回忆具体细节、决定、代码或历史上下文。

    scope: 'all'（全部聊天）| 'side'（仅旁聊）| 'main'（仅主聊天历史）。
    """
    cfg = _cfg(config)
    pool = cfg.get("pool")
    user_id = str(cfg.get("user_id") or "")
    cleaned = (query or "").strip()
    if not cleaned:
        return json.dumps({"results": [], "error": "query 不能为空"}, ensure_ascii=False)
    if pool is None or not user_id:
        return json.dumps({"results": [], "note": "History database not configured."}, ensure_ascii=False)

    norm_scope = (scope or "all").strip().lower()
    if norm_scope not in ("all", "side", "main"):
        norm_scope = "all"
    lim = max(1, min(int(limit or 8), 20))
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return json.dumps({"results": [], "error": "无效的 user_id"}, ensure_ascii=False)
    pattern = f"%{_escape_like(cleaned)}%"

    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    emb_client = cfg.get("embedding_client")
    q_vec_lit: str | None = None
    if emb_client is not None and getattr(emb_client, "is_configured", False):
        try:
            q_vec = await emb_client.embed_query(cleaned)
            if q_vec:
                q_vec_lit = "[" + ",".join(f"{float(v):.8f}" for v in q_vec) + "]"
        except Exception:
            q_vec_lit = None

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # 1. Search side-chat digests (semantic vector + FTS + ILIKE)
                if norm_scope in ("all", "side"):
                    digest_rows: list[Any] = []
                    if q_vec_lit:
                        try:
                            await cur.execute(
                                """
                                SELECT d.conversation_id, d.title, d.summary, d.key_facts, d.last_message_at
                                FROM conversation_digests d
                                WHERE d.user_id = %s
                                  AND (
                                      d.title ILIKE %s ESCAPE '\\'
                                      OR d.summary ILIKE %s ESCAPE '\\'
                                      OR d.search_tsv @@ plainto_tsquery('simple', %s)
                                      OR (d.embedding IS NOT NULL AND (d.embedding <=> %s::vector) < 0.72)
                                  )
                                ORDER BY
                                    CASE WHEN d.embedding IS NOT NULL THEN d.embedding <=> %s::vector ELSE 1.0 END ASC,
                                    d.last_message_at DESC NULLS LAST
                                LIMIT %s
                                """,
                                (user_uuid, pattern, pattern, cleaned, q_vec_lit, q_vec_lit, lim),
                            )
                            digest_rows = await cur.fetchall()
                        except Exception:
                            digest_rows = []
                    if not digest_rows:
                        await cur.execute(
                            """
                            SELECT d.conversation_id, d.title, d.summary, d.key_facts, d.last_message_at
                            FROM conversation_digests d
                            WHERE d.user_id = %s
                              AND (
                                  d.title ILIKE %s ESCAPE '\\'
                                  OR d.summary ILIKE %s ESCAPE '\\'
                                  OR d.search_tsv @@ plainto_tsquery('simple', %s)
                              )
                            ORDER BY d.last_message_at DESC NULLS LAST, d.updated_at DESC
                            LIMIT %s
                            """,
                            (user_uuid, pattern, pattern, cleaned, lim),
                        )
                        digest_rows = await cur.fetchall()
                    for row in digest_rows:
                        cid = str(row[0])
                        seen_keys.add(f"digest:{cid}")
                        results.append(
                            {
                                "match_type": "digest",
                                "conversation_id": cid,
                                "kind": "side",
                                "title": str(row[1] or ""),
                                "snippet": str(row[2] or "")[:400],
                                "key_facts": row[3] if isinstance(row[3], list) else [],
                                "timestamp": row[4].isoformat() if row[4] is not None else None,
                            }
                        )

                # 2. Search episodic message_chunks (semantic vector + pg_trgm + FTS)
                if len(results) < lim:
                    chunk_kind_clause = "AND mc.conversation_kind = %s" if norm_scope in ("side", "main") else ""
                    chunk_rows: list[Any] = []
                    if q_vec_lit:
                        c_params: list[Any] = [user_uuid, q_vec_lit, pattern, cleaned]
                        if norm_scope in ("side", "main"):
                            c_params.append(norm_scope)
                        c_params.extend([q_vec_lit, lim])
                        try:
                            await cur.execute(
                                f"""
                                SELECT mc.id, mc.conversation_id, mc.conversation_kind,
                                       COALESCE(c.title, '') AS title, mc.context_header, mc.content, mc.created_at
                                FROM message_chunks mc
                                INNER JOIN conversations c ON c.id = mc.conversation_id
                                WHERE mc.user_id = %s
                                  AND (
                                      (mc.embedding IS NOT NULL AND (mc.embedding <=> %s::vector) < 0.72)
                                      OR mc.content ILIKE %s ESCAPE '\\'
                                      OR mc.search_tsv @@ plainto_tsquery('simple', %s)
                                  )
                                  {chunk_kind_clause}
                                ORDER BY
                                    CASE WHEN mc.embedding IS NOT NULL THEN mc.embedding <=> %s::vector ELSE 1.0 END ASC,
                                    mc.created_at DESC
                                LIMIT %s
                                """,
                                tuple(c_params),
                            )
                            chunk_rows = await cur.fetchall()
                        except Exception:
                            chunk_rows = []
                    for row in chunk_rows:
                        key = f"chunk:{row[0]}"
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        results.append(
                            {
                                "match_type": "episodic_turn",
                                "conversation_id": str(row[1]),
                                "kind": str(row[2] or "side"),
                                "title": str(row[3] or ""),
                                "context_header": str(row[4] or ""),
                                "snippet": str(row[5] or "")[:450],
                                "timestamp": row[6].isoformat() if row[6] is not None else None,
                            }
                        )
                        if len(results) >= lim:
                            break

                # 3. Search raw verbatim messages across side chats and/or main chat
                kind_clause = ""
                params: list[Any] = [user_uuid, pattern]
                if norm_scope in ("side", "main"):
                    kind_clause = "AND c.kind = %s"
                    params.append(norm_scope)
                params.append(lim * 2)
                await cur.execute(
                    f"""
                    SELECT m.id, m.conversation_id, c.kind, c.title, m.role, m.content, m.created_at
                    FROM messages m
                    INNER JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.user_id = %s
                      AND m.role IN ('user', 'assistant')
                      AND m.status NOT IN ('failed', 'cancelled')
                      AND m.content ILIKE %s ESCAPE '\\'
                      {kind_clause}
                    ORDER BY m.created_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                for row in await cur.fetchall():
                    mid = str(row[0])
                    if mid in seen_keys:
                        continue
                    seen_keys.add(mid)
                    content = str(row[5] or "")
                    idx = content.lower().find(cleaned.lower())
                    if idx >= 0:
                        start = max(0, idx - 120)
                        end = min(len(content), idx + len(cleaned) + 240)
                        snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
                    else:
                        snippet = content[:360]
                    results.append(
                        {
                            "match_type": "message",
                            "message_id": mid,
                            "conversation_id": str(row[1]),
                            "kind": str(row[2] or "side"),
                            "title": str(row[3] or ""),
                            "role": str(row[4] or ""),
                            "snippet": snippet,
                            "timestamp": row[6].isoformat() if row[6] is not None else None,
                        }
                    )
                    if len(results) >= lim:
                        break
    except Exception as exc:
        return json.dumps({"results": [], "error": f"检索历史聊天失败: {exc}"}, ensure_ascii=False)

    return json.dumps({"query": cleaned, "count": len(results), "results": results[:lim]}, ensure_ascii=False)


@tool
async def read_conversation_history(
    conversation_id: str,
    limit: int = 20,
    offset: int = 0,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """按 conversation_id 读取某条旁聊或主聊天中的真实历史对话消息（按时间顺序分页）。"""
    cfg = _cfg(config)
    pool = cfg.get("pool")
    user_id = str(cfg.get("user_id") or "")
    if pool is None or not user_id:
        return json.dumps({"messages": [], "error": "History database not configured."}, ensure_ascii=False)
    try:
        user_uuid = uuid.UUID(user_id)
        conv_uuid = uuid.UUID(str(conversation_id))
    except ValueError:
        return json.dumps({"messages": [], "error": "无效的 conversation_id"}, ensure_ascii=False)

    lim = max(1, min(int(limit or 20), 40))
    off = max(0, int(offset or 0))

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, kind, title FROM conversations WHERE id = %s AND user_id = %s LIMIT 1",
                    (conv_uuid, user_uuid),
                )
                conv_row = await cur.fetchone()
                if conv_row is None:
                    return json.dumps({"messages": [], "error": "对话不存在或无权访问"}, ensure_ascii=False)

                await cur.execute(
                    """
                    SELECT id, role, content, created_at
                    FROM messages
                    WHERE conversation_id = %s
                      AND role IN ('user', 'assistant')
                      AND status NOT IN ('failed', 'cancelled')
                    ORDER BY created_at ASC, id ASC
                    OFFSET %s
                    LIMIT %s
                    """,
                    (conv_uuid, off, lim),
                )
                msg_rows = await cur.fetchall()
    except Exception as exc:
        return json.dumps({"messages": [], "error": f"读取对话历史失败: {exc}"}, ensure_ascii=False)

    messages_out = [
        {
            "message_id": str(r[0]),
            "role": str(r[1]),
            "content": str(r[2] or "")[:1500] + ("…" if len(str(r[2] or "")) > 1500 else ""),
            "created_at": r[3].isoformat() if r[3] is not None else None,
        }
        for r in msg_rows
    ]
    return json.dumps(
        {
            "conversation_id": str(conv_row[0]),
            "kind": str(conv_row[1] or "side"),
            "title": str(conv_row[2] or ""),
            "offset": off,
            "count": len(messages_out),
            "messages": messages_out,
        },
        ensure_ascii=False,
    )


_POSITIVE_USER_REACTIONS = frozenset({"like", "love", "sparkle", "insightful"})


@tool
async def react_to_user_message(
    reaction: Literal["like", "love", "sparkle", "insightful"],
    note: str = "",
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """对用户当前这条消息给出轻量的正向鼓励/点赞回应（仅限正向：like👍 / love❤️ / sparkle✨ / insightful💡）。

    严禁任何负面评价。仅当用户提出独到见解、高质量问题、清晰上下文或表达友好致谢时偶尔使用，避免每轮滥用。
    """
    cfg = _cfg(config)
    if not bool(cfg.get("ai_reactions_enabled", True)):
        return json.dumps({"ok": False, "reason": "ai_reactions_disabled"}, ensure_ascii=False)
    cleaned = str(reaction or "").strip().lower()
    if cleaned not in _POSITIVE_USER_REACTIONS:
        return json.dumps(
            {"ok": False, "error": "仅允许使用正向鼓励表情 (like, love, sparkle, insightful)"},
            ensure_ascii=False,
        )
    cleaned_note = str(note or "").strip()[:120]
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(
            {
                "type": "message.reaction",
                "author_type": "assistant",
                "reaction": cleaned,
                "note": cleaned_note,
            }
        )
    except Exception:
        pass
    return json.dumps({"ok": True, "reaction": cleaned, "note": cleaned_note}, ensure_ascii=False)


def get_builtin_tools(
    *,
    include_delegation: bool = True,
    include_hitl: bool = True,
    include_cross_chat: bool = False,
    include_user_reaction: bool = True,
) -> list[BaseTool]:
    tools: list[BaseTool] = [
        rag_search_workspace,
        memory_search,
        memory_propose,
        todo_list,
        web_search,
        web_extract,
        http_request,
        skill_view,
        request_deep_thinking,
    ]
    if include_user_reaction:
        tools.append(react_to_user_message)
    if include_cross_chat:
        tools.extend([search_chat_history, read_conversation_history])
    if include_hitl:
        tools.extend([clarify, execute_code])
    if include_delegation:
        tools.append(delegate_subtask)
    return tools
