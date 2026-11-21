from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger("whitz.agent.mcp")

_MCP_TOOL_CACHE_TTL = 120.0
_MCP_TOOL_CACHE: dict[str, tuple[float, list[BaseTool]]] = {}


async def load_whitz_mcp_tools(
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
    timeout_seconds: float = 10.0,
) -> list[BaseTool]:
    """Connect to Whitz internal MCP endpoints (/files and /skills) with short TTL caching & timeout."""
    base = (internal_mcp_base_url or "").strip().rstrip("/")
    if not base or not agent_namespace or not agent_api_key:
        return []

    cache_key = hashlib.sha256(f"{base}|{agent_namespace}|{agent_api_key}".encode("utf-8")).hexdigest()[:24]
    now = time.monotonic()
    cached = _MCP_TOOL_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _MCP_TOOL_CACHE_TTL:
        return list(cached[1])

    headers = {
        "Authorization": f"Bearer {agent_api_key}",
        "X-Whitz-Profile": agent_namespace,
        "X-Whitz-Namespace": agent_namespace,
    }
    connections: dict[str, dict[str, Any]] = {
        "whitz_files": {
            "transport": "streamable_http",
            "url": f"{base}/api/internal/mcp/files",
            "headers": headers,
        },
        "whitz_skills": {
            "transport": "streamable_http",
            "url": f"{base}/api/internal/mcp/skills",
            "headers": headers,
        },
        "whitz_schedules": {
            "transport": "streamable_http",
            "url": f"{base}/api/internal/mcp/schedules",
            "headers": headers,
        },
    }

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(connections)
        tools = await asyncio.wait_for(client.get_tools(), timeout=timeout_seconds)
        tool_list = list(tools)
        if tool_list:
            # Evict expired entries occasionally
            if len(_MCP_TOOL_CACHE) > 256:
                _MCP_TOOL_CACHE.clear()
            _MCP_TOOL_CACHE[cache_key] = (now, tool_list)
        return tool_list
    except Exception as exc:
        logger.warning("Failed to load MCP tools from %s: %s", base, exc)
        return []
