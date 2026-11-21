"""Built-in, sandbox, and MCP tools for the Whitz agent."""

from __future__ import annotations

import json
from typing import Any


def parse_tool_error(content: Any, status: str | None = None) -> str | None:
    """Extract a concise error message from a tool output payload or explicit error status."""
    if status == "error":
        return str(content or "tool error")

    obj: dict[str, Any] | None = None
    if isinstance(content, dict):
        obj = content
    elif isinstance(content, str):
        raw = content.strip()
        if raw.startswith("<untrusted_tool_result"):
            end_tag = raw.find(">")
            if end_tag >= 0:
                raw = raw[end_tag + 1 :]
        suffix = "</untrusted_tool_result>"
        if raw.rstrip().endswith(suffix):
            raw = raw.rstrip()[: -len(suffix)].strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                obj = parsed
        except (json.JSONDecodeError, ValueError):
            obj = None

    if not isinstance(obj, dict):
        return None
    if obj.get("error"):
        return str(obj["error"])
    if obj.get("ok") is False:
        if obj.get("status_code"):
            reason = str(obj.get("reason_phrase") or "").strip()
            return f"HTTP {obj['status_code']} {reason}".strip()
        return str(obj.get("message") or obj.get("reason") or "request failed")
    if obj.get("status") == "denied":
        return str(obj.get("message") or "审批被拒绝")
    exit_code = obj.get("exit_code")
    if isinstance(exit_code, int) and exit_code != 0:
        stderr = str(obj.get("stderr") or "").strip()
        return stderr[:300] if stderr else f"exit_code={exit_code}"
    return None

