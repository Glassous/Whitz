from __future__ import annotations

from typing import Any

from app.services.chat.types import get_tool_meta, summarize_tool_call


def normalize_control_payload(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize approval.request / clarify.request payloads consistently across Path A, B, and C."""
    detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
    out: dict[str, Any] = {
        "kind": "approval" if event_name == "approval.request" else "clarify",
        "request_id": payload.get("request_id") or payload.get("prompt_id") or "",
        "execution_generation": payload.get("execution_generation"),
        "tool": payload.get("tool"),
        "preview": payload.get("preview"),
        "detail": detail,
    }
    if isinstance(detail, dict):
        if detail.get("code") is not None:
            out["code"] = detail.get("code")
        if detail.get("language") is not None:
            out["language"] = detail.get("language")
        desc = detail.get("reason") or detail.get("description")
        if desc is not None:
            out["description"] = desc
    return out


def normalize_passthrough_event(
    ev_name: str,
    payload: dict[str, Any],
    *,
    assistant_id_str: str = "",
    assistant_created_at: str | None = None,
    conv_pending_control: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Normalize raw agent events for Path C cross-worker reconnect so schemas match Path A/B."""
    data = dict(payload or {})
    if ev_name == "thinking.delta":
        text = data.get("delta") or data.get("text") or ""
        return "reasoning.delta", {
            "text": text,
            "step": data.get("step"),
            "title": data.get("title") or "",
        }
    if ev_name == "reasoning.delta":
        text = data.get("delta") or data.get("text") or ""
        return "reasoning.delta", {
            "text": text,
            "step": data.get("step"),
            "title": data.get("title") or "",
        }
    if ev_name == "message.delta":
        text = data.get("delta") or data.get("text") or ""
        return "message.delta", {"text": text}
    if ev_name == "message.interim":
        return "commentary", {
            "text": data.get("text") or data.get("delta") or "",
            "step": data.get("step"),
            "title": data.get("title") or "",
            "already_streamed": bool(data.get("already_streamed", False)),
        }
    if ev_name in ("approval.request", "clarify.request"):
        return ev_name, normalize_control_payload(ev_name, data)
    if ev_name in ("tool.started", "tool.completed"):
        tool = str(data.get("tool") or "tool")
        label, ui_kind = get_tool_meta(tool)
        data.setdefault("label", label)
        data.setdefault("ui_kind", ui_kind)
        data.setdefault(
            "summary",
            summarize_tool_call(tool, data.get("args"), data.get("result") or data.get("preview"), data.get("error")),
        )
        return ev_name, data
    if ev_name == "run.snapshot":
        if assistant_id_str:
            data.setdefault("assistant_message_id", assistant_id_str)
        if assistant_created_at:
            data.setdefault("created_at", assistant_created_at)
        if not data.get("pending_control") and isinstance(data.get("pending_controls"), list):
            ctls = data["pending_controls"]
            raw_ctl = ctls[0] if ctls else conv_pending_control
            if isinstance(raw_ctl, dict):
                ctl_ev = "approval.request" if raw_ctl.get("kind") == "approval" else "clarify.request"
                data["pending_control"] = normalize_control_payload(ctl_ev, raw_ctl)
        return "run.snapshot", data
    return ev_name, data
