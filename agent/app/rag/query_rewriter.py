from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from whitz_rag.types import RagScope

from app.core.config import get_settings
from app.core.models import ModelRouter

logger = logging.getLogger("whitz.agent.rag_rewrite")

_TRIVIAL_INPUTS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "你好",
        "您好",
        "在吗",
        "谢谢",
        "感谢",
        "ok",
        "okay",
        "好的",
        "好",
        "嗯",
        "收到",
        "明白",
        "继续",
        "thanks",
        "thank you",
    }
)
_INLINE_FILE_RE = re.compile(r"\[\[file:([0-9a-fA-F-]{36})\|([^\]]+)\]\]")
_DEICTIC_RE = re.compile(
    r"(它|它们|这[份个段页篇张条表]|那[份个段页篇张条表]|上面|上述|刚才|刚刚|前面|之前|上次|上回|那个|该文件|该文档|按我|照我|"
    r"\b(?:it|its|this|that|these|those|above|previous|earlier|last time)\b)",
    re.IGNORECASE,
)
_FILE_INTENT_RE = re.compile(
    r"(文件|文档|资料|附件|pdf|docx|xlsx|csv|报告|合同|表格|截图|图片|代码|源码|项目里|第\s*\d+\s*[页行段章])",
    re.IGNORECASE,
)
_MEMORY_INTENT_RE = re.compile(
    r"(我的|偏好|习惯|风格|记住|记得|项目|背景|身份|技术栈|要求|之前说过|一直|通常|默认|my\b|prefer|remember)",
    re.IGNORECASE,
)
_CHAT_INTENT_RE = re.compile(
    r"(上次|之前|聊过|讨论过|旁聊|主聊|历史|那次|前几天|昨天|上周|上个月|earlier|last chat|discussed)",
    re.IGNORECASE,
)


@dataclass
class QueryPlan:
    should_prefetch: bool = False
    queries: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    attached_file_ids: list[str] = field(default_factory=list)
    used_llm_rewrite: bool = False
    skipped_reason: str | None = None


def _extract_last_user_text(messages: Sequence[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            if (getattr(msg, "additional_kwargs", None) or {}).get("whitz_ephemeral_media"):
                continue
            content = msg.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [
                    str(b.get("text") or "")
                    for b in content
                    if isinstance(b, dict)
                    and b.get("type") in ("text", None)
                    and not str(b.get("text") or "").startswith("<attached_file ")
                ]
                return " ".join(p.strip() for p in parts if p.strip()).strip()
    return ""


def _strip_inline_file_tokens(text: str) -> tuple[str, list[str]]:
    file_ids: list[str] = []

    def _repl(match: re.Match[str]) -> str:
        file_ids.append(match.group(1))
        return f"《{match.group(2)}》"

    cleaned = _INLINE_FILE_RE.sub(_repl, text or "").strip()
    return cleaned, list(dict.fromkeys(file_ids))


def _recent_context_snippet(messages: Sequence[BaseMessage], max_turns: int = 4) -> str:
    lines: list[str] = []
    # Exclude the latest HumanMessage (already passed as current query)
    history = list(messages[:-1]) if messages else []
    for msg in history[-(max_turns * 2) :]:
        if isinstance(msg, HumanMessage):
            if (getattr(msg, "additional_kwargs", None) or {}).get("whitz_ephemeral_media"):
                continue
            if isinstance(msg.content, str) and msg.content.strip():
                lines.append(f"用户：{msg.content.strip()[:220]}")
            elif isinstance(msg.content, list):
                txt = " ".join(
                    str(b.get("text") or "").strip()
                    for b in msg.content
                    if isinstance(b, dict)
                    and b.get("type") in ("text", None)
                    and not str(b.get("text") or "").startswith("<attached_file ")
                ).strip()
                if txt:
                    lines.append(f"用户：{txt[:220]}")
        elif isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            lines.append(f"助手：{msg.content.strip()[:220]}")
    return "\n".join(lines[-6:])


async def build_query_plan(
    *,
    messages: Sequence[BaseMessage],
    rag_scope: RagScope,
    attachments: Sequence[dict[str, Any]],
    directly_delivered_file_ids: Sequence[str] = (),
    memory_enabled: bool,
    memory_index: str,
    conversation_kind: str,
    router: ModelRouter | None = None,
    allow_llm_rewrite: bool = True,
) -> QueryPlan:
    """Layered L0/L1/L2 query planner for Loop 1 proactive prefetch.

    - L0 (0ms): Skip trivial greetings, empty input, or `rag_scope.mode == 'off'`.
    - L1 (0ms): Deterministic source routing from attachments, inline file refs, memory & chat signals.
      Files already directly delivered in this turn (native image/PDF or full-text injected) are excluded
      from redundant prefetch so TTFT drops and models focus on the native input.
    - L2 (~250ms, on-demand): Fast LLM anaphora resolution & multi-query decomposition ONLY when
      multi-turn history + deictic markers / complex comparison exist.
    """
    if rag_scope.mode == "off":
        return QueryPlan(should_prefetch=False, skipped_reason="rag_scope_off")

    raw_query = _extract_last_user_text(messages)
    if not raw_query:
        return QueryPlan(should_prefetch=False, skipped_reason="empty_query")

    cleaned_query, inline_fids = _strip_inline_file_tokens(raw_query)
    low = cleaned_query.lower().strip("!！。.~～?？ ")
    if not low or (low in _TRIVIAL_INPUTS and not inline_fids):
        return QueryPlan(should_prefetch=False, skipped_reason="trivial_greeting")

    direct_set = {str(fid).strip() for fid in (directly_delivered_file_ids or ()) if str(fid).strip()}
    all_attached_fids = list(
        dict.fromkeys(
            [
                *rag_scope.file_ids,
                *inline_fids,
                *[str(a.get("file_id") or a.get("id")) for a in attachments if a.get("attached") and (a.get("file_id") or a.get("id"))],
            ]
        )
    )
    # Exclude files already presented natively or in full in the current HumanMessage
    searchable_attached_fids = [fid for fid in all_attached_fids if fid not in direct_set]
    other_library_files = [
        a for a in attachments if str(a.get("file_id") or a.get("id") or "") not in direct_set
    ]
    has_searchable_files = bool(searchable_attached_fids or other_library_files)
    has_any_memory = bool(memory_enabled and (memory_index or "").strip())

    # If the user sent ONLY directly-delivered media/docs with a short prompt (e.g. image-only or "帮我看下这张图"),
    # skip proactive RAG prefetch unless they explicitly ask about memory or past chats.
    is_direct_attachment_only_turn = bool(direct_set) and not searchable_attached_fids

    # Determine target sources
    sources: list[str] = []
    if rag_scope.mode == "files_only":
        if has_searchable_files:
            sources.append("file")
    else:
        if has_searchable_files:
            if searchable_attached_fids:
                sources.append("file")
            elif not is_direct_attachment_only_turn and (_FILE_INTENT_RE.search(cleaned_query) or len(cleaned_query) >= 12):
                sources.append("file")
        if rag_scope.include_memory and has_any_memory and (
            _MEMORY_INTENT_RE.search(cleaned_query) or (not is_direct_attachment_only_turn and len(cleaned_query) >= 10)
        ):
            sources.append("memory")
        if rag_scope.include_chats and (
            _CHAT_INTENT_RE.search(cleaned_query) or (conversation_kind == "main" and not is_direct_attachment_only_turn)
        ):
            sources.append("chat")

    if not sources:
        return QueryPlan(
            should_prefetch=False,
            skipped_reason="directly_delivered_native" if is_direct_attachment_only_turn else "no_applicable_sources",
        )

    plan = QueryPlan(
        should_prefetch=True,
        queries=[cleaned_query[:500]],
        sources=sources,
        attached_file_ids=searchable_attached_fids,
    )

    # L2: On-demand Fast LLM rewrite ONLY when multi-turn context + anaphora/deictic reference exist
    settings = get_settings()
    has_prior_turns = sum(1 for m in messages if isinstance(m, HumanMessage)) >= 2
    needs_rewrite = (
        allow_llm_rewrite
        and settings.rag_query_rewrite_enabled
        and router is not None
        and bool(settings.llm_model.strip())
        and not settings.llm_base_url.strip().startswith("http://llm.test")
        and has_prior_turns
        and (bool(_DEICTIC_RE.search(cleaned_query)) or len(cleaned_query) >= 90)
    )
    if not needs_rewrite:
        return plan

    history_ctx = _recent_context_snippet(messages)
    if not history_ctx:
        return plan

    try:
        llm, _ = await router.get_chat_model("fast", task_hint="classify", temperature=0.0, max_tokens=180, streaming=False)
        prompt = (
            "你是检索查询改写器。根据近期对话历史，消除当前用户问题中的代词指代（如“它/这份/上面/上次”），"
            "生成 1-2 个清晰独立的检索查询语句，并判断需要检索的知识源（从 file, memory, chat 中选择）。\n"
            '仅输出单行 JSON：{"queries":["独立检索词1"],"sources":["file","memory"]}\n\n'
            f"近期对话：\n{history_ctx}\n\n当前问题：{cleaned_query[:400]}"
        )
        resp = await asyncio.wait_for(llm.ainvoke([HumanMessage(content=prompt)]), timeout=3.5)
        raw = resp.content if isinstance(resp.content, str) else ""
        s_idx, e_idx = raw.find("{"), raw.rfind("}")
        if s_idx >= 0 and e_idx > s_idx:
            parsed = json.loads(raw[s_idx : e_idx + 1])
            rw_queries = [str(q).strip()[:300] for q in (parsed.get("queries") or []) if str(q).strip()][:2]
            if rw_queries:
                plan.queries = rw_queries
                plan.used_llm_rewrite = True
            if rag_scope.mode != "files_only" and isinstance(parsed.get("sources"), list):
                allowed = set(sources)
                # Keep original attached files always included
                refined = [str(s).strip().lower() for s in parsed["sources"] if str(s).strip().lower() in allowed]
                if searchable_attached_fids and "file" not in refined and "file" in allowed:
                    refined.insert(0, "file")
                if refined:
                    plan.sources = list(dict.fromkeys(refined))
    except Exception as exc:
        logger.debug("L2 query rewrite skipped (%s); using original query", exc)

    return plan
