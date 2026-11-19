from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger("whitz.agent.mcp")


async def load_whitz_mcp_tools(
    *,
    internal_mcp_base_url: str,
    agent_namespace: str,
    agent_api_key: str,
) -> list[BaseTool]:
    """Connect to Whitz internal MCP endpoints (/files and /skills) via MultiServerMCPClient."""
    base = (internal_mcp_base_url or "").strip().rstrip("/")
    if not base or not agent_namespace or not agent_api_key:
        return []

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
    }

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(connections)
        tools = await client.get_tools()
        return list(tools)
    except Exception as exc:
        logger.warning("Failed to load MCP tools from %s: %s", base, exc)
        return []
