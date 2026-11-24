from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.config import get_settings
from app.core.models import ModelRouter
from app.graph.state import AgentState
from app.graph.subgraphs import build_coder_subgraph, build_researcher_subgraph
from app.graph.topology import GRAPH_NODES
from app.rag.citations import CitationRegistry, emit_rag_context_event
from app.rag.query_rewriter import build_query_plan
from app.tools.builtin_tools import (
    HITL_TOOL_NAMES,
    SUBAGENT_TOOL_NAMES,
    get_builtin_tools,
)
from app.tools.sandbox import DisabledSandboxExecutor
from whitz_rag.types import RagScope

logger = logging.getLogger("whitz.agent.graph")

SYSTEM_CONTEXT_MSG_ID = "whitz-system-context"
DEFAULT_MAX_TOOL_ITERATIONS = 30
_NODE_LABELS = {n["id"]: n["label"] for n in GRAPH_NODES}
_NUMBERED_PREFIX_RE = re.compile(r"^\s*\d+[.、)）]\s*")


def _looks_like_subquestions(items: list[str]) -> bool:
    """Detect when a model mistakenly puts numbered/question sentences into `options`."""
    if len(items) < 2:
        return False
    q_marks = sum(1 for item in items if "?" in item or "？" in item)
    if q_marks >= max(2, (len(items) + 1) // 2):
        return True
    numbered = sum(1 for item in items if _NUMBERED_PREFIX_RE.match(item))
    long_items = sum(1 for item in items if len(item) >= 24)
    return numbered >= 2 and long_items >= 2


def _normalize_clarify_args(args: dict[str, Any]) -> dict[str, Any]:
    """Normalize clarify tool args into a unified structure supporting single/multi questions & options."""
    top_question = str(args.get("question") or "").strip()
    multiple = bool(args.get("multiple"))
    raw_options = (
        [str(o).strip() for o in args.get("options") or [] if str(o).strip()]
        if isinstance(args.get("options"), list)
        else []
    )
    raw_questions = args.get("questions") if isinstance(args.get("questions"), list) else []

    normalized_questions: list[dict[str, Any]] = []
    if raw_questions:
        for idx, item in enumerate(raw_questions):
            if isinstance(item, dict):
                q_text = str(item.get("question") or item.get("title") or item.get("prompt") or "").strip()
                if not q_text:
                    continue
                q_id = str(item.get("id") or f"q{idx + 1}").strip() or f"q{idx + 1}"
                q_opts = (
                    [str(o).strip() for o in item.get("options") or [] if str(o).strip()]
                    if isinstance(item.get("options"), list)
                    else []
                )
                q_multi = bool(item.get("multiple"))
                q_custom = True if item.get("allow_custom") is None else bool(item.get("allow_custom"))
                q_placeholder = str(item.get("placeholder")).strip() if item.get("placeholder") else None
                normalized_questions.append(
                    {
                        "id": q_id,
                        "question": q_text,
                        "options": q_opts,
                        "multiple": q_multi,
                        "allow_custom": q_custom,
                        "placeholder": q_placeholder,
                    }
                )
            elif isinstance(item, str) and item.strip():
                normalized_questions.append(
                    {
                        "id": f"q{idx + 1}",
                        "question": item.strip(),
                        "options": [],
                        "multiple": False,
                        "allow_custom": True,
                        "placeholder": None,
                    }
                )
    elif raw_options and _looks_like_subquestions(raw_options):
        for idx, text in enumerate(raw_options):
            normalized_questions.append(
                {
                    "id": f"q{idx + 1}",
                    "question": text,
                    "options": [],
                    "multiple": False,
                    "allow_custom": True,
                    "placeholder": None,
                }
            )
        raw_options = []

    if not normalized_questions:
        fallback_q = top_question or "请补充更多信息以便继续。"
        normalized_questions = [
            {
                "id": "q1",
                "question": fallback_q,
                "options": raw_options,
                "multiple": multiple,
                "allow_custom": True,
                "placeholder": None,
            }
        ]

    resolved_question = top_question or (
        normalized_questions[0]["question"]
        if len(normalized_questions) == 1
        else "请补充以下信息以便继续："
    )
    return {
        "question": resolved_question,
        "options": raw_options,
        "multiple": multiple,
        "questions": normalized_questions,
        "preview": resolved_question,
    }


def _emit_node_running(node: str, *, route: str | None = None, model: str | None = None) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer(
            {
                "type": "graph.node",
                "node": node,
                "status": "running",
                "label": _NODE_LABELS.get(node, node),
                "route": route,
                "model": model,
            }
        )
    except Exception:
        pass

_WEEKDAYS_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def format_current_time(tz_name: str | None = None) -> str:
    cleaned = (tz_name or "").strip() or "Asia/Shanghai"
    try:
        tz: Any = ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError):
        cleaned = "Asia/Shanghai"
        try:
            tz = ZoneInfo(cleaned)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    weekday = _WEEKDAYS_ZH[now.weekday()]
    # Minute-level granularity preserves LLM KV prefix caching across rapid multi-turn interactions
    return f"{now.strftime('%Y-%m-%d %H:%M')}（{weekday}，{cleaned}）"


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")


def _estimate_message_tokens(msg: BaseMessage) -> int:
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        text = " ".join(
            str(b.get("text") or b.get("thinking") or "") if isinstance(b, dict) else str(b)
            for b in content
        )
    else:
        text = str(content or "")
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    tc_overhead = 0
    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
        tc_overhead = len(json.dumps(msg.tool_calls, ensure_ascii=False, default=str)) // 3
    return max(4, int(math.ceil(cjk * 0.72 + other * 0.28)) + tc_overhead + 6)


def _base_agent_prompt(assistant_name: str = "Whitz", *, is_main_chat: bool = False) -> str:
    name = (assistant_name or "").strip() or "Whitz"
    extra_main = (
        "\n   - 你当前处于用户的「主聊天」模式，是用户的专属长期助手，天然记得主聊天历史与全部旁聊的关键进展；"
        "当用户提及过去某次旁聊或早期对话的精确细节、参数、代码或决定，而当前摘要不足时，主动调用 `search_chat_history` 与 `read_conversation_history` 按需查阅原文。"
        if is_main_chat
        else ""
    )
    return (
        f"你是 {name} 智能助理，一个自主决策的多智能体工作台助手。\n"
        "你可以根据任务复杂度自主决定下一步行动，并严格遵守以下原则：\n"
        "1. 事实与时效性约束：始终以「当前时间」为基准理解“今天/今年/最近/当前”等时间概念；涉及具体日期、外部动态、文件正文、检索结果或代码运行结论时，必须先调用对应工具查证，严禁编造未验证的数据、链接、文件名或行号。\n"
        "2. 工具与 RAG 自主选择：\n"
        "   - 简单问答直接简洁、准确作答，避免过度铺垫；\n"
        "   - 知识库主动预召回与统一深检：系统已根据当前问题自动预召回高相关证据（见下方「本轮知识库预召回证据」，编号为 `[S1]`、`[S2]`…）。若预召回已充分回答问题，请直接作答避免重复检索；若信息不足或需多跳核实，优先调用 `knowledge_search` 一次性跨源联合检索（文件+记忆+历史对话），或按需调用 `rag_search_workspace` / `memory_search` / `search_chat_history` / `read_workspace_file`；若未命中可主动改用 `list_workspace_files` / `search_workspace_files` 自愈排查；\n"
        "   - 引用溯源规范：当你在回答中引用了预召回证据或检索工具返回的具体事实、数据、条款或历史结论时，请在对应句子或要点末尾标注内联引用标记 `[[cite:S1]]`（多条引用用 `[[cite:S1,S2]]`），编号必须严格对应真实返回结果中的 `citation_id`，严禁编造编号；\n"
        "   - 用户消息中若出现 `[[file:<file_id>|<filename>]]` 标记，代表用户在该语义位置显式引用了对应工作区文件，可直接用其中的 `<file_id>` 调用 `read_workspace_file` 或 `edit_workspace_file`，并严格结合该文件在句子中的位置理解用户意图；\n"
        "   - 工作区文件创建与修改：创建新文本产物或整体重写时调用 `write_workspace_file`；对工作区已有纯文本/代码/Markdown/HTML/CSV 文件做局部修改时，优先调用 `edit_workspace_file`（支持精准文本替换或行区间修补），避免全量重写导致截断；\n"
        "   - 交付产物卡片规范：当需要向用户交付结构化报告、交互式网页、数据表格、长篇文档或代码文件等纯文本产物时，你可自主选择最合适的纯文本格式（如 `.html`、`.md`、`.csv`、`.txt`、`.json`、代码文件等），先调用 `write_workspace_file` 写入工作区获取 `file_id`，再在回复正文合适位置插入如下专用代码块，前端会自动渲染为可点击的交互卡片并在弹窗中展示（HTML 支持沙箱预览与主题联动，CSV 支持可视化表格编辑）：\n"
        "     ```deliverable\n"
        "     {\"file_id\": \"<返回的file_id>\", \"filename\": \"report.html\", \"title\": \"简明交付标题\", \"summary\": \"一句话说明核心内容\"}\n"
        "     ```\n"
        "     请勿在正文中倾倒数百行原始 HTML/CSV/长文档源码，正文仅做核心解读并嵌入交付卡片即可；\n"
        "   - 多主题记忆集与 RAG：参考下方「记忆集目录索引」，需要回忆背景时优先调用 `memory_search`（支持按 `collection` 过滤做混合 RAG 检索）或 `memory_list` 查阅明细；当用户表达长期偏好、项目背景或需要更新/删除记忆时，可直接调用 `memory_propose`（支持 `add` / `replace` / `remove`，并可按需自动归类到新主题集）或 `memory_manage_collection` 管理记忆集，无需额外向用户请求同意；"
        f"{extra_main}\n"
        "   - 需要实时外部资料时使用 `web_search`，可根据查询目标自主选择搜索引擎 `provider`：`\"bocha\"`（博查 AI 搜索，响应快，最适合国内新闻、中文资料、国内企业与政策等）或 `\"tavily\"`（速度较慢但最适合国外英文资料、国际新闻、海外技术社区与英文文档）；若需兼顾国内外对比可并行调用两次 `web_search`，摘要不足时再调用 `web_extract` 精读关键页面；\n"
        "   - 需要调用公开 HTTP/REST API、发送自定义 Method/Headers/Query/JSON/表单请求或查看响应状态码与响应头（等效 curl 能力）时，直接调用 `http_request`；\n"
        "   - 复杂多步骤任务使用 `todo_list` 维护进度计划，或通过 `delegate_subtask` 委派给 `researcher` / `coder` 子智能体；\n"
        "   - 需要精确计算或验证代码时调用 `execute_code`（系统会自动暂停等待用户审批）；遇到关键歧义时调用 `clarify` 向用户追问（单个问题用 `question` + 可选答案 `options`，多个独立问题务必使用 `questions` 列表分项提问）；\n"
        "   - 若技能摘要与当前任务相关，调用 `skill_view` 按需加载完整技能指南后再执行；\n"
        "   - 当用户希望设置周期提醒或自动定时执行某项任务时，可调用 `list_scheduled_tasks`、`create_scheduled_task`、`update_scheduled_task`、`delete_scheduled_task` 管理定时任务（变更会生成待确认卡片由用户确认生效）；\n"
        "   - 当用户提出精彩见解、高质量背景描述或友好致谢且工具可用时，可适度调用 `react_to_user_message` 给出正向点赞（`like`/`love`/`sparkle`/`insightful`，严禁负面回应，勿每轮刷屏）。\n"
        "3. 思考模式自主升档：若当前处于常规非思考模式，但你在分析或工具返回中发现逻辑复杂、信息矛盾或需要深度推演，可调用 `request_deep_thinking` 立即开启深度思考模式再继续作答。\n"
        "4. 回复质量规范：复杂调研、对比或技术方案采用「核心结论前置 + 清晰分点 + 来源引用」结构；简单问题直击要点、简明自然。"
    )


def _prepare_llm_messages(
    messages: list[Any],
    *,
    recent_keep: int = 8,
    old_tool_char_limit: int = 600,
    max_prompt_tokens: int | None = None,
    max_verbatim_messages: int | None = None,
) -> list[BaseMessage]:
    """Keep fresh system context at index 0, fold stale tool outputs, and enforce a safe token budget."""
    sys_msg: SystemMessage | None = None
    non_sys: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            if getattr(m, "id", None) == SYSTEM_CONTEXT_MSG_ID or sys_msg is None:
                sys_msg = m
        else:
            non_sys.append(m)

    # Fold oversized ToolMessages older than the most recent few messages
    cutoff = max(0, len(non_sys) - recent_keep)
    folded_non_sys: list[BaseMessage] = []
    for idx, m in enumerate(non_sys):
        if idx < cutoff and isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > old_tool_char_limit:
            folded = m.content[:old_tool_char_limit] + f"\n... [历史工具输出已折叠，原长 {len(m.content)} 字符]"
            folded_non_sys.append(
                ToolMessage(
                    content=folded,
                    tool_call_id=m.tool_call_id,
                    name=m.name,
                    status=getattr(m, "status", "success"),
                    id=m.id,
                )
            )
        else:
            folded_non_sys.append(m)

    # Group into turn-aligned blocks starting at HumanMessage so trimming never splits tool_call/ToolMessage pairs
    turns: list[list[BaseMessage]] = []
    for m in folded_non_sys:
        if isinstance(m, HumanMessage) or not turns:
            turns.append([m])
        else:
            turns[-1].append(m)

    # Keep turns from newest backwards under max_verbatim_messages and max_prompt_tokens
    sys_tokens = _estimate_message_tokens(sys_msg) if sys_msg is not None else 0
    budget = max(2000, int(max_prompt_tokens) - sys_tokens) if max_prompt_tokens else None
    msg_cap = max(2, int(max_verbatim_messages)) if max_verbatim_messages else None

    kept_turns: list[list[BaseMessage]] = []
    used_tokens = 0
    used_msgs = 0

    for idx in range(len(turns) - 1, -1, -1):
        turn = turns[idx]
        turn_tokens = sum(_estimate_message_tokens(m) for m in turn)
        is_latest_turn = idx == len(turns) - 1
        if not is_latest_turn:
            if msg_cap is not None and used_msgs + len(turn) > msg_cap:
                break
            if budget is not None and used_tokens + turn_tokens > budget:
                break
        kept_turns.append(turn)
        used_tokens += turn_tokens
        used_msgs += len(turn)

    kept_turns.reverse()
    windowed: list[BaseMessage] = [m for turn in kept_turns for m in turn]

    # Guard against leading orphaned ToolMessages if input history didn't begin with HumanMessage
    while windowed and isinstance(windowed[0], ToolMessage):
        windowed.pop(0)

    prepared: list[BaseMessage] = []
    if sys_msg is not None:
        prepared.append(sys_msg)
    prepared.extend(windowed)
    return prepared


def _extract_text(content: Any) -> str:
    """Safely extract text from either string or multimodal list-of-blocks AIMessage content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in ("text", "output_text", None):
                t = item.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "".join(parts)
    return ""


def _merge_usage(acc: dict[str, int] | None, msg: AIMessage) -> dict[str, int]:
    merged = dict(acc or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    step_prompt = 0
    step_comp = 0
    step_total = 0
    meta = getattr(msg, "usage_metadata", None) or {}
    if isinstance(meta, dict):
        step_prompt = int(meta.get("input_tokens") or meta.get("prompt_tokens") or 0)
        step_comp = int(meta.get("output_tokens") or meta.get("completion_tokens") or 0)
        step_total = int(meta.get("total_tokens") or 0)
    if step_total == 0 and step_prompt == 0 and step_comp == 0:
        resp_meta = getattr(msg, "response_metadata", None) or {}
        if isinstance(resp_meta, dict):
            tok = resp_meta.get("token_usage") or resp_meta.get("usage") or {}
            if isinstance(tok, dict):
                step_prompt = int(tok.get("prompt_tokens") or 0)
                step_comp = int(tok.get("completion_tokens") or 0)
                step_total = int(tok.get("total_tokens") or 0)
    if step_total == 0 and (step_prompt or step_comp):
        step_total = step_prompt + step_comp
    merged["prompt_tokens"] += step_prompt
    merged["completion_tokens"] += step_comp
    merged["total_tokens"] += step_total
    return merged


def _build_system_prompt(state: AgentState, cfg: dict[str, Any], current_time_str: str | None = None) -> str:
    """Assemble system prompt in prefix-cache-friendly order: static/stable prefix first, dynamic turn suffix last."""
    is_main = str(state.get("conversation_kind") or cfg.get("conversation_kind") or "side") == "main"
    assistant_name = str(state.get("assistant_name") or cfg.get("assistant_name") or "").strip() or "Whitz"

    # --- Stable Prefix (maximizes LLM KV prefix-cache hit rate) ---
    sections: list[str] = [_base_agent_prompt(assistant_name, is_main_chat=is_main)]

    persona = str(state.get("persona") or "").strip()
    if persona:
        sections.append(f"## 用户定制人设\n{persona}")

    profile_ctx = str(state.get("profile_context") or "").strip()
    if profile_ctx:
        sections.append(f"## 用户授权档案上下文\n{profile_ctx}")

    pinned_memories = str(state.get("pinned_memories") or "").strip()
    if pinned_memories and bool(state.get("memory_enabled", True)):
        sections.append(
            "## 核心常驻记忆（L0 · 每轮始终遵循，无需检索）\n"
            f"{pinned_memories}"
        )

    rolling_summary = str(state.get("rolling_summary") or "").strip()
    if rolling_summary:
        label = "主聊天工作态与历史进展" if is_main else "当前对话工作态与历史进展"
        sections.append(f"## {label}（L1 · 更早细节可查预召回或调用 search_chat_history）\n{rolling_summary}")

    skills = list(state.get("skills") or [])
    requested_skills = set(str(s) for s in (state.get("requested_skills") or []))
    if skills:
        lines = ["以下技能已启用（需要详细步骤时请调用 `skill_view(name)`）："]
        for sk in skills:
            name = str(sk.get("name") or "")
            desc = str(sk.get("description") or "")
            tag = " [本轮用户显式指定]" if name in requested_skills else ""
            lines.append(f"- `{name}`{tag}: {desc}")
        sections.append("## 可用技能摘要\n" + "\n".join(lines))
    elif requested_skills:
        sections.append(
            "## 本轮用户显式指定技能\n" + ", ".join(f"`{s}`" for s in sorted(requested_skills))
        )

    memory_enabled = bool(state.get("memory_enabled", True))
    require_confirm = bool(state.get("memory_require_confirm", False))
    memory_index = str(state.get("memory_index") or "").strip()
    if memory_enabled:
        mode_note = (
            "写入需用户界面确认（propose）"
            if require_confirm
            else "可直接读取、写入、修改、删除与管理记忆集（无需用户同意）"
        )
        mem_section = f"## 长期记忆策略\n记忆功能已开启（{mode_note}）。"
        if memory_index:
            mem_section += f"\n\n### 记忆集目录索引\n{memory_index}"
        sections.append(mem_section)
    else:
        sections.append("## 长期记忆策略\n显式长期记忆条目写入未开启，请勿调用 `memory_propose`。")

    # --- Dynamic Per-Turn Suffix ---
    tz_name = str(state.get("timezone") or cfg.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    now_str = current_time_str or str(cfg.get("current_time_str") or "").strip() or format_current_time(tz_name)
    sections.append(f"## 当前时间\n{now_str}")

    cross_chat_ctx = str(state.get("cross_chat_context") or "").strip()
    if is_main and cross_chat_ctx:
        sections.append(f"## 跨旁聊全局记忆\n{cross_chat_ctx}")

    conv_id = str(state.get("conversation_id") or cfg.get("conversation_id") or "").strip()
    if conv_id:
        sections.append(f"## 当前工作区\nconversation_id: `{conv_id}` (kind=`{'main' if is_main else 'side'}`)")

    attachments = list(state.get("attachments") or [])
    if attachments:
        lines = [
            "以下为当前工作区及资料库中可用的文件元数据（全资料库共享；未预灌全文，请按需调用 `rag_search_workspace` 或 `read_workspace_file`）："
        ]
        for att in attachments:
            extra_parts: list[str] = []
            if att.get("conversation_title"):
                extra_parts.append(f"from_chat={att.get('conversation_title')}")
            if att.get("qa_snippet"):
                extra_parts.append(f"qa=\"{att.get('qa_snippet')}\"")
            extra_str = (", " + ", ".join(extra_parts)) if extra_parts else ""
            lines.append(
                f"- `{att.get('filename', 'file')}` (file_id=`{att.get('file_id')}`, "
                f"category={att.get('category', 'unknown')}, mime={att.get('mime_type', '')}, "
                f"size={att.get('size_bytes', 0)}B, scope={att.get('scope', 'library')}{extra_str})"
            )
        sections.append("## 资料库与附件文件清单\n" + "\n".join(lines))

    extra_instructions = str(state.get("instructions") or "").strip()
    if extra_instructions:
        sections.append(f"## 本轮附加说明\n{extra_instructions}")

    if not bool(state.get("allow_hitl", cfg.get("allow_hitl", True))):
        sections.append(
            "## 后台定时任务无人值守模式\n"
            "当前运行由定时任务自动触发，用户不在线。请自主使用可用工具直接完成任务并输出完整清晰的最终结果，"
            "切勿调用需要人工审批或追问的工具，也不要向用户发起需要即时回复的提问。"
        )

    rag_scope = RagScope.from_dict(state.get("rag_scope") or cfg.get("rag_scope"))
    if rag_scope.mode == "files_only":
        sections.append(
            "## 严选资料库模式（用户已启用）\n"
            "本轮用户要求严格基于已上传文档与资料库内容作答：请勿参考长期记忆或历史闲聊；"
            "所有关键事实均需附带 `[[cite:Sn]]` 引用出处；若资料中未提及，请明确告知用户资料库中未找到相关依据，切勿凭空补全。"
        )

    return "\n\n".join(sections)


def _format_prefetched_evidence_block(
    evidence_items: list[dict[str, Any]],
    *,
    indexing_files: list[dict[str, Any]],
    max_tokens: int = 3000,
) -> str:
    if not evidence_items and not indexing_files:
        return ""
    lines: list[str] = [
        "## 本轮知识库预召回证据（引用事实时请在句末标注 `[[cite:S1]]`，信息不足可调用 `knowledge_search` 继续深挖）"
    ]
    used_tokens = 32
    source_labels = {
        "file": "文档",
        "memory": "长期记忆",
        "chat_digest": "历史对话摘要",
        "chat_turn": "历史对话片段",
    }
    for item in evidence_items:
        cid = str(item.get("citation_id") or "")
        stype = source_labels.get(str(item.get("source_type") or ""), "资料")
        title = str(item.get("title") or "")
        subtitle = str(item.get("subtitle") or "")
        body = str(item.get("content") or "").strip()
        if not cid or not body:
            continue
        header = f"[{cid}] ({stype}) {title}" + (f" · {subtitle}" if subtitle else "")
        block = f"{header}\n{body}"
        est = max(10, int(math.ceil(len(_CJK_RE.findall(block)) * 0.72 + (len(block) - len(_CJK_RE.findall(block))) * 0.28)))
        if used_tokens + est > max_tokens and len(lines) > 1:
            break
        lines.append(block)
        used_tokens += est

    if indexing_files:
        idx_notes = ", ".join(f"`{f.get('filename')}`({f.get('index_status')})" for f in indexing_files[:4])
        lines.append(f"提示：以下文件仍在后台索引或仅部分索引：{idx_notes}；如涉及这些文件请直接调用 `read_workspace_file` 查阅全文。")

    return "\n\n".join(lines) if len(lines) > 1 else ""


def _pending_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    last_ai_idx = -1
    last_ai: AIMessage | None = None
    for idx in range(len(messages) - 1, -1, -1):
        if isinstance(messages[idx], AIMessage):
            last_ai_idx = idx
            last_ai = messages[idx]
            break
    if last_ai is None or not last_ai.tool_calls:
        return []
    answered_ids = {
        getattr(m, "tool_call_id", None)
        for m in messages[last_ai_idx + 1 :]
        if isinstance(m, ToolMessage)
    }
    return [tc for tc in last_ai.tool_calls if tc.get("id") not in answered_ids]


def _classify_route(state: AgentState) -> str:
    messages = list(state.get("messages") or [])
    pending = _pending_tool_calls(messages)
    tool_count = int(state.get("tool_call_count") or 0)
    max_iters = int(state.get("max_tool_iterations") or DEFAULT_MAX_TOOL_ITERATIONS)

    if pending and tool_count < max_iters:
        names = [str(tc.get("name") or "") for tc in pending]
        if any(n not in HITL_TOOL_NAMES and n not in SUBAGENT_TOOL_NAMES for n in names):
            return "tools"
        if any(n in SUBAGENT_TOOL_NAMES for n in names):
            return "subagent"
        if any(n in HITL_TOOL_NAMES for n in names):
            return "hitl_gate"

    if bool(state.get("memory_enabled", True)) and not bool(state.get("memory_extracted")):
        return "memory_extractor"
    return END


def _route_after_tools_or_subagent(state: AgentState) -> str:
    pending = _pending_tool_calls(list(state.get("messages") or []))
    if not pending:
        return "agent"
    names = [str(tc.get("name") or "") for tc in pending]
    if any(n in SUBAGENT_TOOL_NAMES for n in names):
        return "subagent"
    if any(n in HITL_TOOL_NAMES for n in names):
        return "hitl_gate"
    return "agent"


def build_agent_graph(*, checkpointer: Any = None, store: Any = None):
    researcher_subgraph = build_researcher_subgraph()
    coder_subgraph = build_coder_subgraph()

    async def context_loader(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        _emit_node_running("context_loader")
        cfg = dict(config.get("configurable") or {})
        tz_name = str(state.get("timezone") or cfg.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
        now_str = format_current_time(tz_name)
        if isinstance(config.get("configurable"), dict):
            config["configurable"]["current_time_str"] = now_str

        prompt_text = _build_system_prompt(state, cfg, current_time_str=now_str)
        sys_msg = SystemMessage(id=SYSTEM_CONTEXT_MSG_ID, content=prompt_text)

        router: ModelRouter = cfg.get("model_router") or ModelRouter()
        requested_route = str(state.get("requested_route") or cfg.get("requested_route") or "auto")
        messages = list(state.get("messages") or [])
        thinking_enabled, resolved_route, _ = await router.resolve_thinking_decision(
            requested_route,
            messages,
        )

        max_tool_iters = max(
            1,
            int(state.get("max_tool_iterations") or cfg.get("max_tool_iterations") or DEFAULT_MAX_TOOL_ITERATIONS),
        )
        return {
            "messages": [sys_msg],
            "tool_call_count": 0,
            "max_tool_iterations": max_tool_iters,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "rag_evidence": [],
            "rag_diagnostics": {},
            "memory_extracted": False,
            "thinking_enabled": thinking_enabled,
            "thinking_escalated": False,
            "selected_route": resolved_route,
        }

    async def rag_prefetch(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        """Loop 1: Proactive multi-source Hybrid RAG prefetch with layered L0/L1/L2 query planning."""
        _emit_node_running("rag_prefetch")
        settings = get_settings()
        cfg = dict(config.get("configurable") or {})
        retriever = cfg.get("hybrid_retriever")
        user_id = str(state.get("user_id") or cfg.get("user_id") or "")
        conv_id = str(state.get("conversation_id") or cfg.get("conversation_id") or "")
        rag_scope = RagScope.from_dict(state.get("rag_scope") or cfg.get("rag_scope"))

        if (
            not settings.rag_prefetch_enabled
            or retriever is None
            or not hasattr(retriever, "engine")
            or not retriever.engine.db.is_available
            or not user_id
        ):
            return {"rag_diagnostics": {"stage": "prefetch", "skipped_reason": "unconfigured"}}

        messages = list(state.get("messages") or [])
        router: ModelRouter | None = cfg.get("model_router")
        plan = await build_query_plan(
            messages=messages,
            rag_scope=rag_scope,
            attachments=list(state.get("attachments") or []),
            memory_enabled=bool(state.get("memory_enabled", True)),
            memory_index=str(state.get("memory_index") or ""),
            conversation_kind=str(state.get("conversation_kind") or cfg.get("conversation_kind") or "side"),
            router=router,
            allow_llm_rewrite=settings.rag_query_rewrite_enabled,
        )
        if not plan.should_prefetch:
            return {"rag_diagnostics": {"stage": "prefetch", "skipped_reason": plan.skipped_reason}}

        if isinstance(config.get("configurable"), dict) and plan.attached_file_ids:
            config["configurable"]["attached_file_ids"] = plan.attached_file_ids

        reg: CitationRegistry = cfg.get("citation_registry") or CitationRegistry()
        if isinstance(config.get("configurable"), dict):
            config["configurable"]["citation_registry"] = reg

        try:
            items, diag = await retriever.engine.search_unified(
                user_id=user_id,
                queries=plan.queries,
                sources=plan.sources,
                conversation_id=conv_id,
                attached_file_ids=plan.attached_file_ids,
                file_ids=rag_scope.file_ids or None,
                exclude_current_chat=True,
                top_k=8,
                per_source_k=5,
                expand_neighbors=True,
                enable_corrective=True,
                citation_start_index=reg.next_index,
                stage="prefetch",
            )
        except Exception as exc:
            logger.debug("rag_prefetch failed gracefully: %s", exc)
            return {"rag_diagnostics": {"stage": "prefetch", "skipped_reason": f"error:{exc}"}}

        attached_set = set(plan.attached_file_ids)
        kept = [
            it
            for it in items
            if it.confidence in ("high", "medium")
            or (it.source_type == "file" and (it.source_id in attached_set or rag_scope.mode == "files_only"))
        ]
        if not kept and rag_scope.mode == "files_only" and items:
            kept = items[:3]

        if kept:
            reg.register(kept)

        evidence_dicts = [it.to_dict() for it in kept]
        diag_dict = diag.to_dict()
        diag_dict["used_llm_rewrite"] = plan.used_llm_rewrite

        if kept or diag.indexing_files:
            emit_rag_context_event(
                stage="prefetch",
                citations=reg.all_citations(),
                diagnostics=diag_dict,
            )

        block = _format_prefetched_evidence_block(
            evidence_dicts,
            indexing_files=diag.indexing_files,
            max_tokens=settings.rag_prefetch_max_tokens,
        )
        updates: dict[str, Any] = {
            "rag_evidence": evidence_dicts,
            "rag_diagnostics": diag_dict,
        }
        if block:
            # Append prefetched evidence to the dynamic suffix of SystemMessage (preserves static KV prefix!)
            existing_sys = next(
                (m for m in messages if isinstance(m, SystemMessage) and getattr(m, "id", None) == SYSTEM_CONTEXT_MSG_ID),
                None,
            )
            if existing_sys is not None and isinstance(existing_sys.content, str):
                updated_sys = SystemMessage(
                    id=SYSTEM_CONTEXT_MSG_ID,
                    content=f"{existing_sys.content}\n\n{block}",
                )
                updates["messages"] = [updated_sys]
        return updates

    async def agent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        cfg = dict(config.get("configurable") or {})
        router: ModelRouter = cfg.get("model_router") or ModelRouter()
        mcp_tools: list[BaseTool] = list(cfg.get("mcp_tools") or [])
        is_main = str(state.get("conversation_kind") or cfg.get("conversation_kind") or "side") == "main"
        allow_hitl = bool(state.get("allow_hitl", cfg.get("allow_hitl", True)))
        settings = get_settings()
        include_thinking_tool = not bool(state.get("thinking_enabled")) and settings.llm_thinking_mode != "disabled"
        rag_scope = RagScope.from_dict(state.get("rag_scope") or cfg.get("rag_scope"))
        include_cross_chat = rag_scope.include_chats and rag_scope.mode != "files_only"
        builtin = get_builtin_tools(
            include_delegation=True,
            include_hitl=allow_hitl,
            include_cross_chat=include_cross_chat,
            include_user_reaction=bool(cfg.get("ai_reactions_enabled", True)) and allow_hitl,
        )
        if not include_thinking_tool:
            builtin = [t for t in builtin if t.name != "request_deep_thinking"]

        seen_names: set[str] = set()
        all_tools: list[BaseTool] = []
        for t in [*builtin, *mcp_tools]:
            if t.name not in seen_names:
                seen_names.add(t.name)
                all_tools.append(t)

        max_tokens_budget = settings.main_max_prompt_tokens if is_main else settings.side_max_prompt_tokens
        messages = _prepare_llm_messages(
            list(state.get("messages") or []),
            max_prompt_tokens=max_tokens_budget,
            max_verbatim_messages=settings.recent_verbatim_messages,
        )
        requested_route = str(state.get("selected_route") or state.get("requested_route") or cfg.get("requested_route") or "auto")
        thinking_enabled = bool(state.get("thinking_enabled"))
        candidates = await router.select_candidates(requested_route, messages)
        first_ep = candidates[0] if candidates else None
        _emit_node_running(
            "agent",
            route=first_ep.route if first_ep else None,
            model=first_ep.model if first_ep else None,
        )

        tool_count = int(state.get("tool_call_count") or 0)
        max_iters = int(state.get("max_tool_iterations") or DEFAULT_MAX_TOOL_ITERATIONS)
        tools_exhausted = tool_count >= max_iters
        if tools_exhausted:
            messages = [
                *messages,
                HumanMessage(content="已达到本轮最大工具调用次数，请不再调用工具，直接基于已有信息给出完整最终回答。"),
            ]

        last_exc: Exception | None = None
        for ep in candidates:
            try:
                llm = router.build_chat_model(ep, streaming=True, thinking_enabled=thinking_enabled)
                bound = llm.bind_tools(all_tools) if (all_tools and not tools_exhausted) else llm
                try:
                    response = await bound.ainvoke(messages, config=config)
                except Exception as inner_exc:
                    if router.is_unsupported_thinking_param_error(inner_exc):
                        router.mark_thinking_param_unsupported(ep)
                        llm = router.build_chat_model(ep, streaming=True, include_thinking_params=False)
                        bound = llm.bind_tools(all_tools) if (all_tools and not tools_exhausted) else llm
                        response = await bound.ainvoke(messages, config=config)
                    else:
                        raise

                total_usage = _merge_usage(state.get("usage"), response)
                has_tool_calls = bool(getattr(response, "tool_calls", None))
                final_text = _extract_text(response.content)

                # Self-heal if model returned empty text without tool calls after tool observations
                if not has_tool_calls and not final_text.strip():
                    synthesis_nudge = HumanMessage(
                        content="请基于以上工具结果或已知信息，为用户整理一份完整、准确的最终回答。"
                    )
                    response = await llm.ainvoke([*messages, synthesis_nudge], config=config)
                    total_usage = _merge_usage(total_usage, response)
                    final_text = _extract_text(response.content)

                await router.record_success(ep)
                return {
                    "messages": [response],
                    "selected_route": ep.route,
                    "selected_model": ep.model,
                    "usage": total_usage,
                    "final_output": final_text if not getattr(response, "tool_calls", None) else state.get("final_output", ""),
                }
            except GraphInterrupt:
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning("Model %s (%s) invocation failed: %s", ep.model, ep.route, exc)
                await router.record_failure(ep)

        raise RuntimeError(f"All model endpoints failed: {last_exc}")

    async def _run_single_tool(
        tc: dict[str, Any],
        tool_map: dict[str, BaseTool],
        conv_id: str,
        config: RunnableConfig,
    ) -> tuple[ToolMessage, dict[str, Any] | None, bool, bool]:
        name = str(tc.get("name") or "")
        call_id = str(tc.get("id") or name)
        args = dict(tc.get("args") or {})
        if conv_id and name in (
            "list_workspace_files",
            "read_workspace_file",
            "search_workspace_files",
            "write_workspace_file",
            "create_scheduled_task",
            "update_scheduled_task",
            "delete_scheduled_task",
        ):
            args.setdefault("conversation_id", conv_id)

        tool_obj = tool_map.get(name)
        if tool_obj is None:
            return (
                ToolMessage(
                    tool_call_id=call_id,
                    name=name,
                    content=json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False),
                    status="error",
                ),
                None,
                False,
                True,
            )
        try:
            res = await tool_obj.ainvoke(args, config=config)
            content_str = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
            plan_update = None
            if name == "todo_list":
                try:
                    parsed = json.loads(content_str)
                    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
                        plan_update = {"items": parsed["items"]}
                except (json.JSONDecodeError, ValueError):
                    pass
            had_err = False
            try:
                parsed_res = json.loads(content_str)
                if isinstance(parsed_res, dict) and parsed_res.get("error"):
                    had_err = True
            except (json.JSONDecodeError, ValueError):
                pass
            return (
                ToolMessage(tool_call_id=call_id, name=name, content=content_str),
                plan_update,
                name == "request_deep_thinking",
                had_err,
            )
        except Exception as exc:
            return (
                ToolMessage(
                    tool_call_id=call_id,
                    name=name,
                    content=json.dumps({"error": str(exc)}, ensure_ascii=False),
                    status="error",
                ),
                None,
                False,
                True,
            )

    async def tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        _emit_node_running("tools")
        cfg = dict(config.get("configurable") or {})
        mcp_tools: list[BaseTool] = list(cfg.get("mcp_tools") or [])
        is_main = str(state.get("conversation_kind") or cfg.get("conversation_kind") or "side") == "main"
        builtin = get_builtin_tools(
            include_delegation=False,
            include_hitl=False,
            include_cross_chat=True,
        )
        tool_map = {t.name: t for t in [*builtin, *mcp_tools]}

        pending = _pending_tool_calls(list(state.get("messages") or []))
        standard_calls = [
            tc for tc in pending if tc.get("name") not in HITL_TOOL_NAMES and tc.get("name") not in SUBAGENT_TOOL_NAMES
        ]
        conv_id = str(state.get("conversation_id") or cfg.get("conversation_id") or "")

        results = await asyncio.gather(
            *[_run_single_tool(tc, tool_map, conv_id, config) for tc in standard_calls]
        )

        out_msgs: list[ToolMessage] = []
        updated_plan = state.get("plan")
        escalate_thinking = False
        for msg, plan_update, req_thinking, _had_err in results:
            out_msgs.append(msg)
            if plan_update is not None:
                updated_plan = plan_update
            if req_thinking:
                escalate_thinking = True

        updates: dict[str, Any] = {
            "messages": out_msgs,
            "tool_call_count": int(state.get("tool_call_count") or 0) + len(out_msgs),
        }
        if updated_plan is not None:
            updates["plan"] = updated_plan
        if (
            escalate_thinking
            and not bool(state.get("thinking_enabled"))
            and get_settings().llm_thinking_mode != "disabled"
        ):
            updates["thinking_enabled"] = True
            updates["thinking_escalated"] = True
            if get_settings().llm_reasoning_model.strip():
                updates["selected_route"] = "reasoning"
        return updates

    async def hitl_gate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        _emit_node_running("hitl_gate")
        cfg = dict(config.get("configurable") or {})
        allow_hitl = bool(state.get("allow_hitl", cfg.get("allow_hitl", True)))
        pending = _pending_tool_calls(list(state.get("messages") or []))
        # Process strictly ONE pending HITL call per node invocation so multi-tool interrupts
        # checkpoint cleanly and never replay an already-executed tool on subsequent resumes.
        hitl_calls = [tc for tc in pending if tc.get("name") in HITL_TOOL_NAMES][:1]
        if not allow_hitl and hitl_calls:
            blocked_msgs = [
                ToolMessage(
                    tool_call_id=str(tc.get("id") or tc.get("name") or "hitl"),
                    name=str(tc.get("name") or "hitl"),
                    content=json.dumps(
                        {
                            "status": "blocked",
                            "message": "后台定时任务处于无人值守模式，不支持人工审批或追问工具，请直接基于现有能力完成答复。",
                        },
                        ensure_ascii=False,
                    ),
                    status="error",
                )
                for tc in hitl_calls
            ]
            return {
                "messages": blocked_msgs,
                "tool_call_count": int(state.get("tool_call_count") or 0) + len(blocked_msgs),
            }
        out_msgs: list[ToolMessage] = []
        executor = cfg.get("sandbox_executor") or DisabledSandboxExecutor()
        timeout_sec = int(get_settings().sandbox_timeout_seconds)

        for tc in hitl_calls:
            name = str(tc.get("name") or "")
            call_id = str(tc.get("id") or name)
            args = dict(tc.get("args") or {})

            if name == "clarify":
                clarify_payload = _normalize_clarify_args(args)
                resume_val = interrupt(
                    {
                        "kind": "clarify",
                        "tool": "clarify",
                        "call_id": call_id,
                        **clarify_payload,
                    }
                )
                if isinstance(resume_val, dict):
                    answer = str(resume_val.get("answer") or "")
                    answers = resume_val.get("answers")
                    tool_result: dict[str, Any] = {"answer": answer}
                    if answers:
                        tool_result["answers"] = answers
                else:
                    tool_result = {"answer": str(resume_val or "")}
                out_msgs.append(
                    ToolMessage(
                        tool_call_id=call_id,
                        name="clarify",
                        content=json.dumps(tool_result, ensure_ascii=False),
                    )
                )
            elif name == "execute_code":
                code = str(args.get("code") or "")
                language = str(args.get("language") or "python")
                reason = str(args.get("reason") or "")
                resume_val = interrupt(
                    {
                        "kind": "approval",
                        "tool": "execute_code",
                        "call_id": call_id,
                        "language": language,
                        "code": code,
                        "reason": reason,
                        "preview": {"language": language, "code": code, "reason": reason},
                    }
                )
                if isinstance(resume_val, dict):
                    choice = str(resume_val.get("choice") or "").strip().lower()
                    approved = choice in ("once", "approve", "approved", "allow") or bool(resume_val.get("approved"))
                else:
                    approved = str(resume_val or "").strip().lower() in ("once", "approve", "approved", "true", "yes")

                if approved:
                    result = await executor.execute(code, language=language, timeout_seconds=timeout_sec)
                    payload = result.to_dict()
                else:
                    payload = {"status": "denied", "message": "用户拒绝了代码执行审批。"}

                out_msgs.append(
                    ToolMessage(
                        tool_call_id=call_id,
                        name="execute_code",
                        content=json.dumps(payload, ensure_ascii=False),
                    )
                )

        return {
            "messages": out_msgs,
            "tool_call_count": int(state.get("tool_call_count") or 0) + len(out_msgs),
        }

    async def subagent_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        _emit_node_running("subagent")
        pending = _pending_tool_calls(list(state.get("messages") or []))
        sub_calls = [tc for tc in pending if tc.get("name") in SUBAGENT_TOOL_NAMES]
        usage = dict(state.get("usage") or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

        async def _run_sub(tc: dict[str, Any]) -> tuple[ToolMessage, dict[str, Any], dict[str, Any]]:
            call_id = str(tc.get("id") or "delegate_subtask")
            args = dict(tc.get("args") or {})
            role = str(args.get("role") or "researcher").strip().lower()
            if role not in ("researcher", "coder"):
                role = "researcher"
            task = str(args.get("task") or "").strip()
            context = str(args.get("context") or "").strip()
            subgraph = coder_subgraph if role == "coder" else researcher_subgraph
            sub_res = await subgraph.ainvoke(
                {"role": role, "task": task, "context": context, "messages": []},
                config=config,
            )
            result_text = str(sub_res.get("result") or "")
            sub_usage = sub_res.get("usage") or {}
            msg = ToolMessage(
                tool_call_id=call_id,
                name="delegate_subtask",
                content=json.dumps({"role": role, "result": result_text}, ensure_ascii=False),
            )
            return msg, {"role": role, "task": task, "result": result_text}, sub_usage

        results = await asyncio.gather(*[_run_sub(tc) for tc in sub_calls])
        out_msgs: list[ToolMessage] = []
        outputs: list[dict[str, Any]] = []
        for msg, out_obj, sub_usage in results:
            out_msgs.append(msg)
            outputs.append(out_obj)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[k] = usage.get(k, 0) + int(sub_usage.get(k) or 0)

        return {
            "messages": out_msgs,
            "subagent_outputs": outputs,
            "usage": usage,
            "tool_call_count": int(state.get("tool_call_count") or 0) + len(out_msgs),
        }

    async def memory_extractor(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        _emit_node_running("memory_extractor")
        if not bool(state.get("memory_enabled", True)):
            return {"memory_extracted": True}

        cfg = dict(config.get("configurable") or {})
        manager = cfg.get("memory_manager")
        if manager is None:
            return {"memory_extracted": True}

        # Avoid duplicate proposal if the agent already called memory_propose in this turn.
        messages = list(state.get("messages") or [])
        last_human_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                last_human_idx = i
                break
        turn_msgs = messages[last_human_idx:] if last_human_idx >= 0 else messages[-4:]
        for m in turn_msgs:
            if isinstance(m, ToolMessage) and getattr(m, "name", "") == "memory_propose":
                return {"memory_extracted": True}

        user_text = ""
        assistant_text = ""
        for m in turn_msgs:
            if isinstance(m, HumanMessage) and isinstance(m.content, str):
                user_text = m.content.strip()
            elif isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
                assistant_text = m.content.strip()

        if len(user_text) < 12 or not assistant_text:
            return {"memory_extracted": True}

        router: ModelRouter = cfg.get("model_router") or ModelRouter()
        if not get_settings().llm_model.strip() and not cfg.get("allow_memory_extract_llm"):
            return {"memory_extracted": True}

        try:
            llm, _ = await router.get_chat_model(
                "fast",
                task_hint="memory_extract",
                temperature=0.0,
                streaming=False,
            )
            mem_index_hint = str(state.get("memory_index") or "").strip()
            index_block = f"\n当前记忆集目录：\n{mem_index_hint[:800]}\n" if mem_index_hint else ""
            prompt = (
                "判断本轮对话中用户是否明确表达了值得长期记住的个人偏好、身份背景、项目架构或长期要求。"
                "若无，仅返回 JSON `{\"should_save\": false}`。"
                "若有，返回 JSON `{\"should_save\": true, \"target\": \"memory\"|\"user\"|\"projects\"|\"<主题slug>\", "
                "\"collection_name\": \"可选新集名\", \"title\": \"简短标题\", \"tags\": [\"标签\"], "
                "\"is_core\": false, \"content\": \"一句话精炼记忆\"}`。"
                "注意：仅当信息属于每轮对话都必须遵守的核心个人身份、全局语言/编码硬规则或当前唯一主力项目时，才将 `is_core` 设为 true（其余普通事实一律为 false）。"
                f"{index_block}\n"
                f"用户：{user_text[:1000]}\n助手：{assistant_text[:1000]}"
            )
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            raw = resp.content if isinstance(resp.content, str) else ""
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(raw[start : end + 1])
                if parsed.get("should_save") and parsed.get("content"):
                    cand_content = str(parsed["content"]).strip()
                    cand_target = str(parsed.get("target") or "memory")
                    cand_title = str(parsed.get("title") or "")
                    cand_tags = list(parsed.get("tags") or []) if isinstance(parsed.get("tags"), list) else None
                    cand_col_name = str(parsed.get("collection_name") or "").strip() or None
                    cand_is_core = bool(parsed.get("is_core", False))
                    final_action = "add"
                    old_content_to_replace: str | None = None

                    # Semantic Memory Consolidation: compare against Top-3 similar existing memories
                    if get_settings().rag_memory_consolidation_enabled and cand_content:
                        try:
                            similar = await manager.search(
                                user_id=str(state.get("user_id") or cfg.get("user_id") or ""),
                                agent_namespace=str(state.get("agent_namespace") or cfg.get("agent_namespace") or ""),
                                query=cand_content,
                                memory_enabled=True,
                                limit=3,
                            )
                            if similar:
                                sim_lines = "\n".join(
                                    f"- [{idx + 1}] (集:{m.get('collection')}) {m.get('content')}"
                                    for idx, m in enumerate(similar)
                                )
                                cons_prompt = (
                                    "你是长期记忆冲突消解器。对比【新候选记忆】与【已有相似记忆】，判断应该如何处理：\n"
                                    "- noop：已有记忆已经完整包含相同事实，无需重复写入；\n"
                                    "- add：属于全新补充信息，与已有记忆不冲突；\n"
                                    "- replace：新事实更新/推翻了某条旧记忆（例如用户更换技术栈、改变偏好），需给出被替换的旧记忆编号 index（1开始）与合并更新后的 content。\n"
                                    '仅输出单行 JSON：{"decision":"noop"|"add"|"replace","replace_index":1,"content":"更新后的精炼记忆"}\n\n'
                                    f"已有相似记忆：\n{sim_lines}\n\n新候选记忆：{cand_content}"
                                )
                                c_resp = await llm.ainvoke([HumanMessage(content=cons_prompt)])
                                c_raw = c_resp.content if isinstance(c_resp.content, str) else ""
                                cs, ce = c_raw.find("{"), c_raw.rfind("}")
                                if cs >= 0 and ce > cs:
                                    c_parsed = json.loads(c_raw[cs : ce + 1])
                                    dec = str(c_parsed.get("decision") or "add").strip().lower()
                                    if dec == "noop":
                                        return {"memory_extracted": True}
                                    if dec == "replace":
                                        r_idx = int(c_parsed.get("replace_index") or 1) - 1
                                        if 0 <= r_idx < len(similar):
                                            final_action = "replace"
                                            old_content_to_replace = str(similar[r_idx].get("content") or "")
                                            cand_target = str(similar[r_idx].get("collection") or cand_target)
                                            merged_txt = str(c_parsed.get("content") or "").strip()
                                            if merged_txt:
                                                cand_content = merged_txt
                        except Exception as cons_exc:
                            logger.debug("Memory semantic consolidation skipped: %s", cons_exc)

                    await manager.propose(
                        user_id=str(state.get("user_id") or cfg.get("user_id") or ""),
                        agent_namespace=str(state.get("agent_namespace") or cfg.get("agent_namespace") or ""),
                        conversation_id=str(state.get("conversation_id") or cfg.get("conversation_id") or "") or None,
                        target=cand_target,
                        action=final_action,
                        old_content=old_content_to_replace,
                        title=cand_title,
                        tags=cand_tags,
                        collection_name=cand_col_name,
                        content=cand_content,
                        is_pinned=cand_is_core,
                        priority=1 if cand_is_core else 2,
                        memory_enabled=True,
                        memory_require_confirm=bool(state.get("memory_require_confirm", False)),
                    )
        except Exception as exc:
            logger.debug("Optional memory extraction skipped: %s", exc)

        return {"memory_extracted": True}

    graph = StateGraph(AgentState)
    graph.add_node("context_loader", context_loader)
    graph.add_node("rag_prefetch", rag_prefetch)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("hitl_gate", hitl_gate)
    graph.add_node("subagent", subagent_node)
    graph.add_node("memory_extractor", memory_extractor)

    graph.add_edge(START, "context_loader")
    graph.add_edge("context_loader", "rag_prefetch")
    graph.add_edge("rag_prefetch", "agent")
    graph.add_conditional_edges(
        "agent",
        _classify_route,
        {
            "tools": "tools",
            "hitl_gate": "hitl_gate",
            "subagent": "subagent",
            "memory_extractor": "memory_extractor",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "tools",
        _route_after_tools_or_subagent,
        {"agent": "agent", "subagent": "subagent", "hitl_gate": "hitl_gate"},
    )
    graph.add_conditional_edges(
        "subagent",
        _route_after_tools_or_subagent,
        {"agent": "agent", "hitl_gate": "hitl_gate", "subagent": "subagent"},
    )
    graph.add_conditional_edges(
        "hitl_gate",
        _route_after_tools_or_subagent,
        {"agent": "agent", "hitl_gate": "hitl_gate", "subagent": "subagent"},
    )
    graph.add_edge("memory_extractor", END)

    return graph.compile(checkpointer=checkpointer, store=store)
