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
from pydantic import BaseModel, Field

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
async def knowledge_search(
    query: str,
    sources: list[Literal["file", "memory", "chat"]] | None = None,
    file_id: str | None = None,
    collection: str | None = None,
    top_k: int = 8,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """统一多源混合知识检索（同时覆盖资料库文档、多主题长期记忆与历史对话），支持重排、父子邻域扩展与低置信度自纠错。

    - query: 清晰的语义或关键词查询。
    - sources: 可选知识域列表，默认同时检索 ['file', 'memory', 'chat']；可按需缩小范围。
    - file_id: 可选，限定仅在指定文件内检索。
    - collection: 可选，限定仅在指定记忆集 slug 内检索。
    返回结果每条附带引用编号 citation_id（如 S1、S2），回答引用事实时请使用 [[cite:S1]] 标注出处。
    """
    from app.rag.citations import emit_rag_context_event

    cfg = _cfg(config)
    retriever = cfg.get("hybrid_retriever")
    user_id = str(cfg.get("user_id") or "")
    conversation_id = str(cfg.get("conversation_id") or "")
    if retriever is None or not hasattr(retriever, "engine") or not user_id:
        return json.dumps({"count": 0, "results": [], "note": "Unified RAG engine not configured."}, ensure_ascii=False)

    rag_scope_raw = cfg.get("rag_scope") or {}
    mode = str(rag_scope_raw.get("mode") or "auto").lower()
    req_sources = list(sources or ["file", "memory", "chat"])
    if mode == "files_only":
        req_sources = ["file"]
    elif not bool(cfg.get("memory_enabled", True)):
        req_sources = [s for s in req_sources if s != "memory"]

    reg = cfg.get("citation_registry")
    start_idx = reg.next_index if reg is not None else 1
    attached_fids = list(cfg.get("attached_file_ids") or [])

    items, diag = await retriever.engine.search_unified(
        user_id=user_id,
        queries=[query],
        sources=req_sources,
        conversation_id=conversation_id,
        attached_file_ids=attached_fids,
        file_id=file_id,
        collection=collection,
        exclude_current_chat=False,
        top_k=max(1, min(int(top_k or 8), 20)),
        expand_neighbors=True,
        enable_corrective=True,
        citation_start_index=start_idx,
        stage="tool",
    )

    if reg is not None and items:
        reg.register(items)
        emit_rag_context_event(
            stage="tool",
            citations=reg.all_citations(),
            diagnostics=diag.to_dict(),
        )

    hint = None
    if not items and diag.indexing_files:
        names = ", ".join(f"{f['filename']}({f['index_status']})" for f in diag.indexing_files[:3])
        hint = f"部分文件仍在索引中或仅部分索引（{names}），可直接调用 read_workspace_file 读取原文。"
    elif not items:
        hint = "未命中高相关片段，可尝试换词检索，或调用 list_workspace_files / read_workspace_file / read_conversation_history 查阅原文。"

    payload: dict[str, Any] = {
        "count": len(items),
        "results": [it.to_dict() for it in items],
        "diagnostics": diag.to_dict(),
    }
    if hint:
        payload["hint"] = hint
    return json.dumps(payload, ensure_ascii=False)


@tool
async def rag_search_workspace(
    query: str,
    file_id: str | None = None,
    top_k: int = 8,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """在当前对话工作区和用户的全局共享文件中执行混合检索（向量语义 + 全文检索 + RRF + 重排 + 邻域扩展）。

    当用户提问涉及已上传附件、文档内容或全局资料库时优先调用此工具定位相关片段。
    """
    from app.rag.citations import emit_rag_context_event

    cfg = _cfg(config)
    retriever = cfg.get("hybrid_retriever")
    user_id = str(cfg.get("user_id") or "")
    conversation_id = str(cfg.get("conversation_id") or "")
    if retriever is None or not user_id or not conversation_id:
        return json.dumps({"results": [], "note": "Hybrid RAG retriever not configured."}, ensure_ascii=False)
    attached_fids = list(cfg.get("attached_file_ids") or [])

    if hasattr(retriever, "engine"):
        reg = cfg.get("citation_registry")
        items, diag = await retriever.engine.search_unified(
            user_id=user_id,
            queries=[query],
            sources=["file"],
            conversation_id=conversation_id,
            attached_file_ids=attached_fids,
            file_id=file_id,
            top_k=max(1, min(int(top_k or 8), 20)),
            expand_neighbors=True,
            enable_corrective=True,
            citation_start_index=reg.next_index if reg is not None else 1,
            stage="tool",
        )
        if reg is not None and items:
            reg.register(items)
            emit_rag_context_event(stage="tool", citations=reg.all_citations(), diagnostics=diag.to_dict())
        from app.rag.hybrid_retriever import _evidence_to_chunk_dict

        chunks = [_evidence_to_chunk_dict(it) for it in items]
        return json.dumps({"count": len(chunks), "results": chunks, "diagnostics": diag.to_dict()}, ensure_ascii=False)

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
    collection: str | None = None,
    limit: int = 8,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """混合 RAG 检索用户的多记忆集内容（向量 + 全文 + 模糊三路召回 + RRF + 重排）。

    query: 检索关键词或语义查询。
    collection: 可选，限定检索某个记忆集 slug（如 'memory'、'user'、'projects' 或自定义集 slug）；留空则在全部已启用记忆集中检索。
    """
    cfg = _cfg(config)
    manager = cfg.get("memory_manager")
    if not cfg.get("memory_enabled", True):
        return json.dumps({"enabled": False, "results": []}, ensure_ascii=False)
    if manager is None:
        return json.dumps({"enabled": True, "results": []}, ensure_ascii=False)
    items = await manager.search(
        user_id=str(cfg.get("user_id") or ""),
        agent_namespace=str(cfg.get("agent_namespace") or ""),
        query=query,
        memory_enabled=True,
        collection=collection,
        limit=max(1, min(int(limit or 8), 20)),
    )
    return json.dumps({"enabled": True, "collection": collection, "count": len(items), "results": items}, ensure_ascii=False)


@tool
async def memory_list(
    collection: str | None = None,
    limit: int = 20,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """列出全部记忆集目录，或查看指定记忆集内的完整条目。

    collection: 留空时返回所有记忆集的 slug、名称、描述、条目数与启用状态；传入记忆集 slug 时返回该集内条目列表。
    """
    cfg = _cfg(config)
    manager = cfg.get("memory_manager")
    if not cfg.get("memory_enabled", True):
        return json.dumps({"enabled": False, "collections": [], "entries": []}, ensure_ascii=False)
    if manager is None:
        return json.dumps({"enabled": True, "collections": [], "entries": []}, ensure_ascii=False)
    user_id = str(cfg.get("user_id") or "")
    if not collection:
        cols = await manager.list_collections(user_id=user_id)
        return json.dumps({"enabled": True, "count": len(cols), "collections": cols}, ensure_ascii=False)
    entries = await manager.list_entries(
        user_id=user_id,
        agent_namespace=str(cfg.get("agent_namespace") or ""),
        collection=collection,
        limit=max(1, min(int(limit or 20), 50)),
    )
    return json.dumps({"enabled": True, "collection": collection, "count": len(entries), "entries": entries}, ensure_ascii=False)


@tool
async def memory_propose(
    content: str,
    target: str = "memory",
    action: str = "add",
    old_content: str | None = None,
    title: str = "",
    tags: list[str] | None = None,
    collection_name: str | None = None,
    collection_description: str | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """写入、修改或删除一条长期用户记忆（默认直接生效，无需用户同意）。

    target: 目标记忆集 slug，默认预置 'memory'（通用笔记）、'user'（个人画像与偏好）、'projects'（项目与工作），
            也支持直接指定新主题集 slug（如 'project-whitz'），新增时若不存在会自动创建对应记忆集。
    action: 'add'（新增）| 'replace'（替换修改，需提供准确的 old_content）| 'remove'（删除）。
    title: 可选短标题（便于目录索引与检索）。
    tags: 可选标签列表（如 ['rust', '架构']）。
    collection_name / collection_description: 当 target 为新建记忆集时，可附带中文名称与简介。
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
        title=title,
        tags=tags,
        collection_name=collection_name,
        collection_description=collection_description,
        memory_enabled=bool(cfg.get("memory_enabled", True)),
        memory_require_confirm=bool(cfg.get("memory_require_confirm", False)),
    )
    return json.dumps(res, ensure_ascii=False)


@tool
async def memory_manage_collection(
    action: str,
    slug: str,
    name: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """创建、修改或删除用户的自定义记忆集（无需用户同意）。

    action: 'create'（新建）| 'update'（改名/改简介/启停）| 'delete'（删除自定义集；系统预置集不可删除）。
    slug: 记忆集唯一标识（英文/数字/连字符，如 'project-whitz'）。
    """
    cfg = _cfg(config)
    manager = cfg.get("memory_manager")
    if not cfg.get("memory_enabled", True):
        return json.dumps({"status": "disabled", "message": "用户未开启长期记忆功能。"}, ensure_ascii=False)
    if manager is None:
        return json.dumps({"status": "unavailable", "message": "MemoryManager 未初始化。"}, ensure_ascii=False)
    res = await manager.manage_collection(
        user_id=str(cfg.get("user_id") or ""),
        action=action,
        slug=slug,
        name=name,
        description=description,
        enabled=enabled,
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


_CJK_QUERY_RE = re.compile(r"[\u4e00-\u9fff]")
_TAVILY_TIME_RANGE = {
    "oneDay": "day",
    "oneWeek": "week",
    "oneMonth": "month",
    "oneYear": "year",
}
_VALID_FRESHNESS = frozenset({"noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"})


def _resolve_search_order(
    query: str,
    provider: str,
    *,
    has_bocha: bool,
    has_tavily: bool,
) -> list[str]:
    """Order configured search engines by AI choice or query-language heuristic."""
    choice = (provider or "auto").strip().lower()
    order: list[str] = []
    if choice == "bocha":
        if has_bocha:
            order.append("bocha")
        if has_tavily:
            order.append("tavily")
    elif choice == "tavily":
        if has_tavily:
            order.append("tavily")
        if has_bocha:
            order.append("bocha")
    else:
        prefer_bocha = bool(_CJK_QUERY_RE.search(query or ""))
        candidates = ("bocha", "tavily") if prefer_bocha else ("tavily", "bocha")
        for eng in candidates:
            if eng == "bocha" and has_bocha:
                order.append("bocha")
            elif eng == "tavily" and has_tavily:
                order.append("tavily")
    return order


async def _search_bocha(
    query: str,
    limit: int,
    api_key: str,
    search_url: str,
    freshness: str,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "query": query,
        "freshness": freshness if freshness in _VALID_FRESHNESS else "noLimit",
        "summary": True,
        "count": limit,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(search_url or "https://api.bochaai.com/v1/web-search", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
    code = data.get("code")
    if code is not None and int(code) != 200:
        raise RuntimeError(str(data.get("msg") or f"Bocha error code {code}"))
    payload_data = data.get("data") if isinstance(data.get("data"), dict) else data
    web_pages = payload_data.get("webPages") if isinstance(payload_data.get("webPages"), dict) else {}
    raw_items = web_pages.get("value") if isinstance(web_pages.get("value"), list) else []
    results: list[dict[str, str]] = []
    for r in raw_items[:limit]:
        if not isinstance(r, dict):
            continue
        snippet = str(r.get("summary") or r.get("snippet") or "")[:800]
        entry: dict[str, str] = {
            "title": str(r.get("name") or r.get("title") or "")[:200],
            "url": str(r.get("url") or "")[:500],
            "snippet": snippet,
        }
        if r.get("siteName"):
            entry["site_name"] = str(r["siteName"])[:80]
        if r.get("publishTime") or r.get("dateLastCrawled"):
            entry["published_at"] = str(r.get("publishTime") or r.get("dateLastCrawled"))[:40]
        results.append(entry)
    return {
        "ok": True,
        "provider": "bocha",
        "result_count": len(results),
        "results": results,
    }


async def _search_tavily(
    query: str,
    limit: int,
    api_key: str,
    freshness: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": limit,
        "include_answer": True,
    }
    if freshness in _TAVILY_TIME_RANGE:
        body["time_range"] = _TAVILY_TIME_RANGE[freshness]
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        resp = await client.post("https://api.tavily.com/search", json=body)
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
    return {
        "ok": True,
        "provider": "tavily",
        "result_count": len(results),
        "answer": data.get("answer"),
        "results": results,
    }


async def _search_duckduckgo(query: str, limit: int) -> dict[str, Any]:
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
    return {
        "ok": True,
        "provider": "duckduckgo",
        "result_count": len(results),
        "results": results,
    }


@tool
async def web_search(
    query: str,
    max_results: int = 5,
    provider: Literal["auto", "bocha", "tavily"] = "auto",
    freshness: Literal["noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"] = "noLimit",
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """在互联网上搜索最新信息、文档或新闻。

    支持双搜索引擎并行选择，请根据查询内容自主决定 `provider`：
    - `"bocha"`：博查 AI 搜索，响应速度快，主要适合国内新闻、中文资料、国内企业/政策与中文技术文档；
    - `"tavily"`：Tavily 搜索，响应相对较慢，但适合国外英文资料、国际新闻、海外开源社区与英文学术/文档检索；
    - `"auto"`：自动选择（中文查询优先博查，英文/海外查询优先 Tavily）；若需同时对照国内外资料，可并行调用两次本工具分别指定 `"bocha"` 与 `"tavily"`。
    """
    settings = get_settings()
    limit = max(1, min(int(max_results or 5), 10))
    tavily_key = (settings.search_api_key or "").strip()
    bocha_key = (settings.bocha_api_key or "").strip()
    bocha_url = (getattr(settings, "bocha_search_url", "") or "https://api.bochaai.com/v1/web-search").strip()

    order = _resolve_search_order(
        query,
        provider,
        has_bocha=bool(bocha_key),
        has_tavily=bool(tavily_key),
    )

    fallback_from: str | None = None
    fallback_reason: str | None = None
    req_choice = (provider or "auto").strip().lower()
    if req_choice in ("bocha", "tavily") and (
        (req_choice == "bocha" and not bocha_key) or (req_choice == "tavily" and not tavily_key)
    ):
        fallback_from = req_choice
        fallback_reason = f"{req_choice}_unconfigured"

    for engine in order:
        try:
            if engine == "bocha":
                payload = await _search_bocha(query, limit, bocha_key, bocha_url, freshness)
            else:
                payload = await _search_tavily(query, limit, tavily_key, freshness)
            if fallback_from and fallback_from != engine:
                payload["fallback_from"] = fallback_from
                if fallback_reason:
                    payload["fallback_reason"] = fallback_reason
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            if fallback_from is None:
                fallback_from = engine
                fallback_reason = str(exc)[:200]
            logger.warning("%s web_search failed (%s); falling back", engine, exc)

    # Free fallback via DuckDuckGo Instant Answer API
    try:
        payload = await _search_duckduckgo(query, limit)
        if fallback_from:
            payload["fallback_from"] = fallback_from
            if fallback_reason:
                payload["fallback_reason"] = fallback_reason
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        err_payload: dict[str, Any] = {
            "ok": False,
            "provider": "none",
            "result_count": 0,
            "results": [],
            "error": str(exc),
        }
        if fallback_from:
            err_payload["fallback_from"] = fallback_from
            if fallback_reason:
                err_payload["fallback_reason"] = fallback_reason
        return json.dumps(err_payload, ensure_ascii=False)


@tool
async def web_extract(
    url: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """抓取并提取指定公开网页的纯文本正文内容。"""
    cleaned = (url or "").strip()
    if not await _is_public_url_async(cleaned):
        return json.dumps(
            {"ok": False, "provider": "none", "error": "仅允许抓取合法的公网 HTTP/HTTPS 页面。", "url": cleaned},
            ensure_ascii=False,
        )

    settings = get_settings()
    api_key = (settings.search_api_key or "").strip()
    fallback_from: str | None = None
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
                    {"ok": True, "provider": "tavily", "url": cleaned, "content": content[:12000]},
                    ensure_ascii=False,
                )
        except Exception as exc:
            fallback_from = "tavily"
            logger.warning("Tavily web_extract failed (%s); falling back to HTTP fetch", exc)

    try:
        max_bytes = 512 * 1024
        chunks: list[bytes] = []
        total = 0
        status_code = 200
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=False,
            headers={"User-Agent": "WhitzAgent/1.0"},
        ) as client:
            async with client.stream("GET", cleaned) as resp:
                status_code = resp.status_code
                resp.raise_for_status()
                async for piece in resp.aiter_bytes(chunk_size=16384):
                    chunks.append(piece)
                    total += len(piece)
                    if total >= max_bytes:
                        break
        raw_html = b"".join(chunks).decode("utf-8", errors="replace")
        text = _strip_html(raw_html)
        out_payload: dict[str, Any] = {
            "ok": True,
            "provider": "http",
            "status_code": status_code,
            "url": cleaned,
            "content": text[:12000],
        }
        if fallback_from:
            out_payload["fallback_from"] = fallback_from
        return json.dumps(out_payload, ensure_ascii=False)
    except Exception as exc:
        err_out: dict[str, Any] = {
            "ok": False,
            "provider": "http",
            "url": cleaned,
            "error": f"网页抓取失败: {exc}",
        }
        if fallback_from:
            err_out["fallback_from"] = fallback_from
        return json.dumps(err_out, ensure_ascii=False)


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


class ClarifyQuestionItem(BaseModel):
    id: str | None = Field(default=None, description="问题唯一标识，如 storage_type")
    question: str = Field(description="要向用户确认的具体问题")
    options: list[str] | None = Field(
        default=None,
        description="该问题的可选预设答案列表（仅放候选答案，不要放子问题）",
    )
    multiple: bool = Field(default=False, description="是否允许多选")
    allow_custom: bool = Field(default=True, description="是否允许用户输入自定义文本补充")
    placeholder: str | None = Field(default=None, description="输入框占位提示")


@tool
async def clarify(
    question: str = "",
    options: list[str] | None = None,
    multiple: bool = False,
    questions: list[ClarifyQuestionItem] | None = None,
) -> str:
    """当需求存在关键歧义、缺少必要参数或需要用户做重要取舍时，暂停执行并向用户发起澄清追问。

    使用规范：
    - 单个问题：填写 `question`；如有预设候选答案，填写 `options`（仅放答案选项，不要把子问题放进 `options`）；可按需设置 `multiple=True` 支持多选。
    - 多个问题：使用 `questions` 列表逐项列出每个问题及其可选的 `options`，`question` 可填写简要总引导语。
    """
    # Handled inside hitl_gate node via LangGraph interrupt().
    serialized_questions = [
        q.model_dump(exclude_none=True) if isinstance(q, BaseModel) else q
        for q in (questions or [])
    ]
    return json.dumps(
        {
            "question": question,
            "options": options or [],
            "multiple": multiple,
            "questions": serialized_questions,
        },
        ensure_ascii=False,
    )


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
    """检索用户全部旁聊与历史主聊天记录（摘要 + 情景轮次语义混合检索 + 原始消息全文），用于回忆具体细节、决定、代码或历史上下文。

    scope: 'all'（全部聊天）| 'side'（仅旁聊）| 'main'（仅主聊天历史）。
    """
    from app.rag.citations import emit_rag_context_event

    cfg = _cfg(config)
    pool = cfg.get("pool")
    retriever = cfg.get("hybrid_retriever")
    user_id = str(cfg.get("user_id") or "")
    cleaned = (query or "").strip()
    if not cleaned:
        return json.dumps({"results": [], "error": "query 不能为空"}, ensure_ascii=False)
    if (pool is None and retriever is None) or not user_id:
        return json.dumps({"results": [], "note": "History database not configured."}, ensure_ascii=False)

    norm_scope = (scope or "all").strip().lower()
    if norm_scope not in ("all", "side", "main"):
        norm_scope = "all"
    lim = max(1, min(int(limit or 8), 20))
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return json.dumps({"results": [], "error": "无效的 user_id"}, ensure_ascii=False)

    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # 1. Unified 3-leg Hybrid RAG over conversation_digests + message_chunks (strict HNSW iterative_scan + FTS + trgm + Rerank + MMR)
    if retriever is not None and hasattr(retriever, "engine"):
        try:
            chat_items = await retriever.engine.search_chats(
                user_id=user_id,
                query=cleaned,
                scope=norm_scope,
                top_k=lim,
                apply_rerank=True,
            )
            reg = cfg.get("citation_registry")
            if reg is not None and chat_items:
                reg.register(chat_items)
                emit_rag_context_event(stage="tool", citations=reg.all_citations())
            for it in chat_items:
                seen_keys.add(it.chunk_id)
                meta = it.metadata or {}
                results.append(
                    {
                        "citation_id": it.citation_id,
                        "match_type": "digest" if it.source_type == "chat_digest" else "episodic_turn",
                        "conversation_id": str(meta.get("conversation_id") or it.source_id),
                        "kind": str(meta.get("kind") or "side"),
                        "title": it.title,
                        "snippet": it.snippet,
                        "key_facts": meta.get("key_facts") or [],
                        "score": round(float(it.score), 4),
                        "timestamp": meta.get("timestamp"),
                    }
                )
        except Exception as exc:
            logger.debug("Unified chat RAG leg failed (%s); falling back to verbatim message search", exc)

    # 2. Verbatim raw message ILIKE fallback for exact identifiers/code/error strings
    if pool is not None and len(results) < lim:
        pattern = f"%{_escape_like(cleaned)}%"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
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
            if not results:
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
    include_cross_chat: bool = True,
    include_user_reaction: bool = True,
) -> list[BaseTool]:
    tools: list[BaseTool] = [
        knowledge_search,
        rag_search_workspace,
        memory_search,
        memory_list,
        memory_propose,
        memory_manage_collection,
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
