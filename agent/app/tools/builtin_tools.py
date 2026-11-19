from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import uuid
from typing import Any
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
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return False
    except OSError:
        return False
    return True


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
    if not _is_public_url(cleaned):
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
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            headers={"User-Agent": "WhitzAgent/1.0"},
        ) as client:
            resp = await client.get(cleaned)
            resp.raise_for_status()
            text = _strip_html(resp.text)
        return json.dumps({"url": cleaned, "content": text[:12000]}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"url": cleaned, "error": f"网页抓取失败: {exc}"}, ensure_ascii=False)


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


def get_builtin_tools(*, include_delegation: bool = True, include_hitl: bool = True) -> list[BaseTool]:
    tools: list[BaseTool] = [
        rag_search_workspace,
        memory_search,
        memory_propose,
        todo_list,
        web_search,
        web_extract,
        skill_view,
        request_deep_thinking,
    ]
    if include_hitl:
        tools.extend([clarify, execute_code])
    if include_delegation:
        tools.append(delegate_subtask)
    return tools
