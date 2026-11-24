from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from app.core.models import ModelRouter
from app.graph.state import SubagentState
from app.tools import parse_tool_error
from app.tools.builtin_tools import (
    http_request,
    knowledge_search,
    memory_list,
    memory_search,
    rag_search_workspace,
    search_chat_history,
    skill_view,
    web_extract,
    web_search,
)

logger = logging.getLogger("whitz.agent.subgraphs")

MAX_SUBAGENT_ITERATIONS = 8

_RESEARCHER_ALLOWED_MCP = frozenset(
    {"list_workspace_files", "read_workspace_file", "search_workspace_files", "list_user_skills"}
)
_CODER_ALLOWED_MCP = frozenset(
    {
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_files",
        "write_workspace_file",
    }
)


def _merge_usage(acc: dict[str, int] | None, msg: AIMessage) -> dict[str, int]:
    merged = dict(acc or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    meta = getattr(msg, "usage_metadata", None) or {}
    if isinstance(meta, dict):
        merged["prompt_tokens"] += int(meta.get("input_tokens") or meta.get("prompt_tokens") or 0)
        merged["completion_tokens"] += int(meta.get("output_tokens") or meta.get("completion_tokens") or 0)
        merged["total_tokens"] += int(meta.get("total_tokens") or 0)
    return merged


def _select_subagent_tools(role: str, config: RunnableConfig) -> list[BaseTool]:
    cfg = dict(config.get("configurable") or {})
    mcp_tools: list[BaseTool] = list(cfg.get("mcp_tools") or [])
    allowed_mcp = _CODER_ALLOWED_MCP if role == "coder" else _RESEARCHER_ALLOWED_MCP
    base: list[BaseTool] = [
        knowledge_search,
        rag_search_workspace,
        web_search,
        web_extract,
        http_request,
        skill_view,
    ]
    if role != "coder":
        base.extend([memory_search, memory_list, search_chat_history])
    for t in mcp_tools:
        if t.name in allowed_mcp:
            base.append(t)
    return base


def _emit_subagent_tool_event(payload: dict[str, Any]) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(payload)
    except Exception:
        pass


def _clip_tool_str(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "\n... [truncated]"
    return value


async def _invoke_single_tool(
    tc: dict[str, Any],
    tool_map: dict[str, BaseTool],
    conv_id: str,
    config: RunnableConfig,
) -> ToolMessage:
    name = str(tc.get("name") or "")
    call_id = str(tc.get("id") or name)
    args = dict(tc.get("args") or {})
    if conv_id and name in (
        "list_workspace_files",
        "read_workspace_file",
        "search_workspace_files",
        "write_workspace_file",
    ):
        args.setdefault("conversation_id", conv_id)
    tool_obj = tool_map.get(name)
    if tool_obj is None:
        err_json = json.dumps({"error": f"子智能体无权调用工具: {name}"}, ensure_ascii=False)
        return ToolMessage(
            tool_call_id=call_id,
            name=name,
            content=err_json,
            status="error",
        )

    _emit_subagent_tool_event(
        {
            "type": "tool.started",
            "tool": name,
            "preview": args,
            "args": args,
            "call_id": call_id,
            "status": "running",
        }
    )
    started = time.monotonic()
    try:
        res = await tool_obj.ainvoke(args, config=config)
        text = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
        dur_ms = round((time.monotonic() - started) * 1000.0, 1)
        err = parse_tool_error(text, None)
        _emit_subagent_tool_event(
            {
                "type": "tool.completed",
                "tool": name,
                "preview": _clip_tool_str(text, 8000),
                "args": args,
                "result": _clip_tool_str(text, 24000),
                "error": err,
                "duration": dur_ms,
                "duration_ms": dur_ms,
                "call_id": call_id,
                "status": "failed" if err else "completed",
            }
        )
        return ToolMessage(tool_call_id=call_id, name=name, content=text)
    except Exception as exc:
        dur_ms = round((time.monotonic() - started) * 1000.0, 1)
        err_msg = str(exc)
        err_json = json.dumps({"error": err_msg}, ensure_ascii=False)
        _emit_subagent_tool_event(
            {
                "type": "tool.completed",
                "tool": name,
                "preview": err_json,
                "args": args,
                "result": err_json,
                "error": err_msg,
                "duration": dur_ms,
                "duration_ms": dur_ms,
                "call_id": call_id,
                "status": "failed",
            }
        )
        return ToolMessage(
            tool_call_id=call_id,
            name=name,
            content=err_json,
            status="error",
        )


async def _invoke_tools_for_message(
    last_msg: AIMessage,
    tools: list[BaseTool],
    config: RunnableConfig,
) -> list[ToolMessage]:
    tool_map = {t.name: t for t in tools}
    cfg = dict(config.get("configurable") or {})
    conv_id = str(cfg.get("conversation_id") or "")
    calls = list(last_msg.tool_calls or [])
    if not calls:
        return []
    return list(
        await asyncio.gather(*[_invoke_single_tool(tc, tool_map, conv_id, config) for tc in calls])
    )


def _build_specialist_subgraph(role: str):
    system_prompt = (
        "你是 Whitz 的 Researcher 深度研究子智能体。专注于多跳检索工作区文档、记忆与联网信息，"
        "提供准确、可验证、带引用出处的结构化研究结论。调用 `web_search` 时可根据查询对象自主选择 "
        "`provider=\"bocha\"`（博查 AI 搜索，速度快，擅长国内/中文资料）或 `provider=\"tavily\"`（适合国外/英文资料）。"
        if role == "researcher"
        else "你是 Whitz 的 Coder 工程与数据分析子智能体。专注于阅读工作区数据/代码、编写高质量代码、"
        "产出工作区文件并给出清晰实现说明（如需沙箱运行请在结论中附上建议执行的代码）。调用 `web_search` 时"
        "可根据资料来源自主选择 `provider=\"bocha\"`（国内/中文）或 `provider=\"tavily\"`（海外/英文）。"
    )
    task_hint = "code" if role == "coder" else "research"

    async def worker_node(state: SubagentState, config: RunnableConfig) -> dict[str, Any]:
        cfg = dict(config.get("configurable") or {})
        router: ModelRouter = cfg.get("model_router") or ModelRouter()
        max_iters = max(1, int(state.get("max_iterations") or cfg.get("max_subagent_iterations") or MAX_SUBAGENT_ITERATIONS))
        tools = _select_subagent_tools(role, config)
        orig_messages = list(state.get("messages") or [])
        seed_added = not orig_messages
        if seed_added:
            task_text = str(state.get("task") or "").strip()
            ctx_text = str(state.get("context") or "").strip()
            now_str = str(cfg.get("current_time_str") or "").strip()
            sys_full = f"{system_prompt}\n当前时间：{now_str}" if now_str else system_prompt
            prompt = f"任务：{task_text}"
            if ctx_text:
                prompt += f"\n\n上下文：\n{ctx_text}"
            messages = [SystemMessage(content=sys_full), HumanMessage(content=prompt)]
        else:
            messages = orig_messages

        candidates = await router.select_candidates(
            cfg.get("requested_route", "auto"),
            messages,
            task_hint=task_hint,
        )
        want_thinking = router.settings.llm_thinking_mode != "disabled"
        last_exc: Exception | None = None
        for ep in candidates:
            try:
                llm = router.build_chat_model(ep, streaming=False, thinking_enabled=want_thinking)
                bound = llm.bind_tools(tools) if tools else llm
                try:
                    resp = await bound.ainvoke(messages, config=config)
                except Exception as inner_exc:
                    if router.is_unsupported_thinking_param_error(inner_exc):
                        router.mark_thinking_param_unsupported(ep)
                        llm = router.build_chat_model(ep, streaming=False, include_thinking_params=False)
                        bound = llm.bind_tools(tools) if tools else llm
                        resp = await bound.ainvoke(messages, config=config)
                    else:
                        raise
                await router.record_success(ep)
                return {
                    "messages": [*messages, resp] if seed_added else [resp],
                    "iterations": int(state.get("iterations") or 0) + 1,
                    "max_iterations": max_iters,
                    "usage": _merge_usage(state.get("usage"), resp),
                }
            except Exception as exc:
                last_exc = exc
                await router.record_failure(ep)
        fallback_msg = AIMessage(content=f"子智能体调用模型失败: {last_exc}")
        return {
            "messages": [*messages, fallback_msg] if seed_added else [fallback_msg],
            "iterations": int(state.get("iterations") or 0) + 1,
            "max_iterations": max_iters,
        }

    async def tools_node(state: SubagentState, config: RunnableConfig) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        last_msg = messages[-1] if messages else None
        if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
            return {}
        tools = _select_subagent_tools(role, config)
        tool_msgs = await _invoke_tools_for_message(last_msg, tools, config)
        return {"messages": tool_msgs}

    async def synthesizer_node(state: SubagentState) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        final_text = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
                final_text = msg.content.strip()
                break
        if not final_text:
            final_text = "子智能体已完成检索但未生成文本结论。"
        return {"result": final_text}

    def route_worker(state: SubagentState) -> str:
        messages = list(state.get("messages") or [])
        last_msg = messages[-1] if messages else None
        iterations = int(state.get("iterations") or 0)
        max_iters = max(1, int(state.get("max_iterations") or MAX_SUBAGENT_ITERATIONS))
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls and iterations < max_iters:
            return "tools"
        return "synthesizer"

    graph = StateGraph(SubagentState)
    graph.add_node("worker", worker_node)
    graph.add_node("tools", tools_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_edge(START, "worker")
    graph.add_conditional_edges("worker", route_worker, {"tools": "tools", "synthesizer": "synthesizer"})
    graph.add_edge("tools", "worker")
    graph.add_edge("synthesizer", END)
    return graph.compile()


def build_researcher_subgraph():
    return _build_specialist_subgraph("researcher")


def build_coder_subgraph():
    return _build_specialist_subgraph("coder")
