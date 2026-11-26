from __future__ import annotations

import json
from typing import Any

# Canonical tool metadata shared across server SSE, persisted reasoning, and clients.
TOOL_METADATA: dict[str, dict[str, str]] = {
    "knowledge_search": {"label": "检索知识库", "ui_kind": "search"},
    "rag_search_workspace": {"label": "检索工作区文档", "ui_kind": "search"},
    "search_workspace_files": {"label": "搜索工作区文件", "ui_kind": "search"},
    "search_chat_history": {"label": "检索历史对话", "ui_kind": "search"},
    "read_conversation_history": {"label": "查阅对话记录", "ui_kind": "search"},
    "web_search": {"label": "联网搜索", "ui_kind": "search"},
    "web_extract": {"label": "抓取网页内容", "ui_kind": "search"},
    "http_request": {"label": "发起 HTTP 请求", "ui_kind": "http"},
    "list_workspace_files": {"label": "查看工作区文件列表", "ui_kind": "file_read"},
    "inspect_workspace_file": {"label": "查看文件结构", "ui_kind": "file_read"},
    "read_workspace_file": {"label": "读取工作区文件", "ui_kind": "file_read"},
    "write_workspace_file": {"label": "写入工作区文件", "ui_kind": "file_write"},
    "edit_workspace_file": {"label": "编辑工作区文件", "ui_kind": "file_write"},
    "execute_code": {"label": "执行沙箱代码", "ui_kind": "code"},
    "memory_search": {"label": "检索长期记忆", "ui_kind": "memory"},
    "memory_list": {"label": "查看长期记忆", "ui_kind": "memory"},
    "memory_propose": {"label": "提炼长期记忆", "ui_kind": "memory"},
    "memory_manage_collection": {"label": "管理记忆集合", "ui_kind": "memory"},
    "todo_list": {"label": "更新执行计划", "ui_kind": "plan"},
    "delegate_subtask": {"label": "委派子智能体", "ui_kind": "subagent"},
    "clarify": {"label": "向用户确认细节", "ui_kind": "generic"},
    "request_deep_thinking": {"label": "切换深度思考", "ui_kind": "generic"},
    "skill_view": {"label": "读取技能说明", "ui_kind": "skill"},
    "list_user_skills": {"label": "查看已安装技能", "ui_kind": "skill"},
    "preview_github_skill": {"label": "预览 GitHub 技能", "ui_kind": "skill"},
    "install_github_skill": {"label": "安装 GitHub 技能", "ui_kind": "skill"},
    "create_user_skill": {"label": "创建自定义技能", "ui_kind": "skill"},
    "list_scheduled_tasks": {"label": "查看定时任务", "ui_kind": "schedule"},
    "get_scheduled_task_runs": {"label": "查看定时执行记录", "ui_kind": "schedule"},
    "create_scheduled_task": {"label": "创建定时任务", "ui_kind": "schedule"},
    "update_scheduled_task": {"label": "更新定时任务", "ui_kind": "schedule"},
    "delete_scheduled_task": {"label": "删除定时任务", "ui_kind": "schedule"},
    "react_to_user_message": {"label": "互动点赞", "ui_kind": "generic"},
}


def get_tool_meta(tool_name: str) -> tuple[str, str]:
    """Return ``(human_label, ui_kind)`` for any builtin or MCP tool name."""
    raw = (tool_name or "tool").strip()
    clean = raw.split("__")[-1] if "__" in raw else raw
    info = TOOL_METADATA.get(raw) or TOOL_METADATA.get(clean)
    if info:
        return info["label"], info["ui_kind"]
    return clean, "generic"


def _try_parse_json(val: Any) -> dict[str, Any] | None:
    if isinstance(val, dict):
        return val
    if isinstance(val, str) and val.lstrip().startswith("{"):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def summarize_tool_call(tool_name: str, args: Any = None, result: Any = None, error: Any = None) -> str:
    """Produce a concise, human-readable 1-line summary for UI step cards."""
    label, ui_kind = get_tool_meta(tool_name)
    if error:
        err_s = str(error).strip()
        return f"{label}失败：{err_s[:80]}"

    args_d = _try_parse_json(args) or {}
    res_d = _try_parse_json(result) or {}

    if ui_kind == "search":
        q = str(args_d.get("query") or args_d.get("url") or "").strip()
        hits = res_d.get("results") or res_d.get("items") or res_d.get("hits") or res_d.get("matches")
        hit_note = f" · 命中 {len(hits)} 条" if isinstance(hits, list) else ""
        if q:
            return f"{label}「{q[:40]}」{hit_note}"
        return f"{label}{hit_note}"

    if ui_kind in ("file_read", "file_write"):
        fname = str(res_d.get("filename") or args_d.get("filename") or args_d.get("file_id") or "").strip()
        if fname:
            return f"{label}：{fname[:60]}"
        return label

    if ui_kind == "code":
        lang = str(args_d.get("language") or res_d.get("language") or "python")
        if "exit_code" in res_d:
            return f"执行 {lang} 代码 · 退出码 {res_d.get('exit_code')}"
        return f"执行 {lang} 代码"

    if ui_kind == "subagent":
        role = str(args_d.get("role") or res_d.get("role") or "researcher")
        task = str(args_d.get("task") or "").strip()
        return f"委派 {role}：{task[:50]}" if task else f"委派 {role} 子智能体"

    if ui_kind == "http":
        method = str(args_d.get("method") or "GET").upper()
        url = str(args_d.get("url") or res_d.get("url") or "").strip()
        sc = res_d.get("status_code")
        sc_note = f" ({sc})" if sc is not None else ""
        return f"{method} {url[:50]}{sc_note}" if url else f"{label}{sc_note}"

    return label


def merge_citations(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge citation lists across RAG stages without losing earlier prefetch citations."""
    merged: list[dict[str, Any]] = []
    by_id: dict[str, int] = {}
    for src_list in (existing, incoming):
        for raw in src_list or ():
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            cid = str(item.get("citation_id") or item.get("id") or "")
            key = cid or f"{item.get('source_type')}:{item.get('source_id')}:{item.get('locator')}"
            if key in by_id:
                merged[by_id[key]] = {**merged[by_id[key]], **item}
            else:
                by_id[key] = len(merged)
                merged.append(item)
    return merged


def finalize_plan_status(plan: dict[str, Any] | None, terminal_status: str) -> dict[str, Any] | None:
    """Auto-close dangling ``in_progress`` plan steps when a run terminates cleanly or fails."""
    if not isinstance(plan, dict):
        return plan
    items = plan.get("items")
    if not isinstance(items, list):
        return plan
    target = "completed" if terminal_status == "completed" else "cancelled"
    new_items: list[dict[str, Any]] = []
    changed = False
    for it in items:
        if isinstance(it, dict):
            st = str(it.get("status") or "").lower()
            if st == "in_progress":
                new_items.append({**it, "status": target})
                changed = True
            else:
                new_items.append(dict(it))
    return {"items": new_items} if changed else plan
