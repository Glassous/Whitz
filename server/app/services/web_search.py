"""Lightweight server-side web search service (Bocha -> Tavily -> DuckDuckGo fallback)."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("whitz.web_search")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_VALID_FRESHNESS = frozenset({"noLimit", "oneDay", "oneWeek", "oneMonth", "oneYear"})
_TAVILY_TIME_RANGE = {
    "oneDay": "day",
    "oneWeek": "week",
    "oneMonth": "month",
    "oneYear": "year",
}


def _resolve_order(query: str, *, has_bocha: bool, has_tavily: bool) -> list[str]:
    prefer_bocha = bool(_CJK_RE.search(query or ""))
    candidates = ("bocha", "tavily") if prefer_bocha else ("tavily", "bocha")
    order: list[str] = []
    for eng in candidates:
        if eng == "bocha" and has_bocha:
            order.append("bocha")
        elif eng == "tavily" and has_tavily:
            order.append("tavily")
    return order


async def _search_bocha(
    query: str,
    *,
    limit: int,
    api_key: str,
    search_url: str,
    freshness: str,
) -> list[dict[str, str]]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "query": query,
        "freshness": freshness if freshness in _VALID_FRESHNESS else "oneWeek",
        "summary": True,
        "count": limit,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0), trust_env=False) as client:
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
    for item in raw_items[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()[:500]
        title = str(item.get("name") or item.get("title") or "").strip()[:200]
        snippet = str(item.get("summary") or item.get("snippet") or "").strip()[:600]
        if not title and not snippet:
            continue
        entry: dict[str, str] = {
            "title": title or url,
            "url": url,
            "snippet": snippet,
            "site_name": str(item.get("siteName") or "").strip()[:80],
            "published_at": str(item.get("publishTime") or item.get("dateLastCrawled") or "").strip()[:40],
        }
        results.append(entry)
    return results


async def _search_tavily(
    query: str,
    *,
    limit: int,
    api_key: str,
    freshness: str,
) -> list[dict[str, str]]:
    body: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": limit,
        "include_answer": False,
    }
    if freshness in _TAVILY_TIME_RANGE:
        body["time_range"] = _TAVILY_TIME_RANGE[freshness]
    async with httpx.AsyncClient(timeout=httpx.Timeout(14.0, connect=5.0), trust_env=False) as client:
        resp = await client.post("https://api.tavily.com/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    results: list[dict[str, str]] = []
    for item in (data.get("results") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()[:500]
        title = str(item.get("title") or "").strip()[:200]
        snippet = str(item.get("content") or "").strip()[:600]
        if not title and not snippet:
            continue
        results.append(
            {
                "title": title or url,
                "url": url,
                "snippet": snippet,
                "site_name": "",
                "published_at": str(item.get("published_date") or "").strip()[:40],
            }
        )
    return results


async def _search_duckduckgo(query: str, *, limit: int) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), trust_env=False) as client:
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
        )
        resp.raise_for_status()
        data = resp.json()
    results: list[dict[str, str]] = []
    abstract = str(data.get("AbstractText") or "").strip()
    abstract_url = str(data.get("AbstractURL") or "").strip()
    if abstract:
        results.append(
            {
                "title": str(data.get("Heading") or query)[:200],
                "url": abstract_url[:500],
                "snippet": abstract[:600],
                "site_name": str(data.get("AbstractSource") or "DuckDuckGo")[:80],
                "published_at": "",
            }
        )
    for topic in data.get("RelatedTopics") or []:
        if len(results) >= limit:
            break
        if isinstance(topic, dict) and topic.get("Text"):
            text_val = str(topic.get("Text") or "").strip()
            results.append(
                {
                    "title": text_val[:120],
                    "url": str(topic.get("FirstURL") or "").strip()[:500],
                    "snippet": text_val[:600],
                    "site_name": "DuckDuckGo",
                    "published_at": "",
                }
            )
    return results[:limit]


async def search_web(
    query: str,
    *,
    max_results: int = 4,
    freshness: str = "oneWeek",
) -> list[dict[str, str]]:
    """Search public web results using configured providers with graceful fallback."""
    cleaned = " ".join((query or "").strip().split())
    if not cleaned:
        return []
    limit = max(1, min(int(max_results or 4), 8))
    settings = get_settings()
    bocha_key = (settings.bocha_api_key or "").strip()
    tavily_key = (settings.search_api_key or "").strip()
    bocha_url = (getattr(settings, "bocha_search_url", "") or "https://api.bochaai.com/v1/web-search").strip()

    order = _resolve_order(cleaned, has_bocha=bool(bocha_key), has_tavily=bool(tavily_key))
    for engine in order:
        try:
            if engine == "bocha":
                items = await _search_bocha(
                    cleaned, limit=limit, api_key=bocha_key, search_url=bocha_url, freshness=freshness
                )
            else:
                items = await _search_tavily(cleaned, limit=limit, api_key=tavily_key, freshness=freshness)
            if items:
                return items
        except Exception as exc:
            logger.warning("web_search engine=%s failed for query=%r: %s", engine, cleaned[:80], exc)

    try:
        return await _search_duckduckgo(cleaned, limit=limit)
    except Exception as exc:
        logger.warning("web_search duckduckgo fallback failed for query=%r: %s", cleaned[:80], exc)
        return []
