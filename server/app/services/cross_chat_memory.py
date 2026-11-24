from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import desc, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.models import (
    Conversation,
    ConversationDigest,
    ConversationEpisode,
    Message,
    MessageChunk,
    User,
    is_pgvector_enabled,
)
from app.db.session import SessionLocal, detect_pgvector
from app.services import embeddings

logger = logging.getLogger("whitz.cross_chat_memory")

MAIN_CONVERSATION_TITLE = "主要聊天"
RECENT_VERBATIM_MESSAGES = 12
COMPACT_TRIGGER_TOKENS = 12000
COMPACT_TRIGGER_MESSAGES = 24
EPISODE_TRIGGER_MESSAGES = 16
EPISODE_TRIGGER_TOKENS = 6000
EPISODE_KEEP_RECENT = 8
EPISODE_GAP_SECONDS = 4 * 3600
EPISODE_GAP_MIN_MESSAGES = 4
CURSOR_HISTORY_MIN_MESSAGES = 10
CURSOR_HISTORY_MAX_MESSAGES = 28
CURSOR_HISTORY_MAX_TOKENS = 8000
ROLLING_SUMMARY_MAX_TOKENS = 2200
ROLLING_SUMMARY_MAX_CHARS = 4800

DIRECTORY_MAX_ITEMS = 8
DIRECTORY_MAX_CHARS = 1500
RECALLED_MAX_ITEMS = 4
RECALLED_MAX_CHARS = 2200

DIGEST_MIN_NEW_MESSAGES = 4
DIGEST_MIN_INTERVAL_SECONDS = 120

_LOW_SIGNAL_USER_MSGS = frozenset(
    {
        "ok",
        "okay",
        "thanks",
        "thank you",
        "thx",
        "好的",
        "好",
        "嗯",
        "嗯嗯",
        "收到",
        "明白",
        "知道了",
        "谢谢",
        "感谢",
        "继续",
        "可以",
        "没问题",
        "行",
        "赞",
        "好的谢谢",
    }
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def estimate_tokens(text_val: str | None) -> int:
    """Fast bilingual token estimator (CJK ~0.7 tok/char, ASCII ~0.28 tok/char)."""
    if not text_val:
        return 0
    s = str(text_val)
    cjk_count = len(_CJK_RE.findall(s))
    other_count = len(s) - cjk_count
    return max(1, int(math.ceil(cjk_count * 0.72 + other_count * 0.28)))


def _clip(text_val: str | None, limit: int) -> str:
    cleaned = " ".join((text_val or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _cosine_sim(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


async def ensure_main_conversation(db: AsyncSession, user: User) -> Conversation:
    """Guarantee that ``user`` has exactly one ``kind='main'`` conversation."""
    existing = (
        await db.execute(
            select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.kind == "main",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    conv = Conversation(
        user_id=user.id,
        thread_id=str(uuid.uuid4()),
        kind="main",
        title=MAIN_CONVERSATION_TITLE,
        is_pinned=False,
    )
    db.add(conv)
    try:
        await db.commit()
        await db.refresh(conv)
        return conv
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(Conversation).where(
                    Conversation.user_id == user.id,
                    Conversation.kind == "main",
                )
            )
        ).scalar_one()
        return existing


def _fast_llm_config() -> tuple[str, str, str] | None:
    settings = get_settings()
    base = (settings.llm_fast_base_url or settings.llm_base_url or "").strip().rstrip("/")
    api_key = (settings.llm_fast_api_key or settings.llm_api_key or "").strip()
    model = (settings.llm_fast_model or settings.llm_model or "").strip()
    if not base or not model or base.startswith("http://llm.test"):
        return None
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    return url, api_key, model


async def _call_fast_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 512,
    temperature: float = 0.1,
    timeout_seconds: float = 20.0,
) -> str | None:
    cfg = _fast_llm_config()
    if cfg is None:
        return None
    url, api_key, model = cfg
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds, connect=5.0), trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                return None
            data = resp.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        msg = choices[0].get("message") if choices and isinstance(choices[0], dict) else None
        content = (msg or {}).get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
            return "".join(parts).strip()
        return None
    except Exception as exc:
        logger.debug("Fast LLM summary call skipped: %s", exc)
        return None


def _extractive_digest(title: str, messages: list[Message]) -> tuple[str, list[str], list[str]]:
    """Zero-cost deterministic fallback digest when fast LLM is unavailable."""
    usable = [
        m
        for m in messages
        if m.role in ("user", "assistant") and (m.content or "").strip() and m.status not in ("failed", "cancelled")
    ]
    if not usable:
        return (title or "空旁聊"), [], []

    first_user = next((m.content for m in usable if m.role == "user"), "")
    last_user = next((m.content for m in reversed(usable) if m.role == "user"), "")
    last_assistant = next((m.content for m in reversed(usable) if m.role == "assistant"), "")

    parts: list[str] = []
    if first_user:
        parts.append(f"起意：{_clip(first_user, 110)}")
    if last_user and last_user != first_user:
        parts.append(f"最新提问：{_clip(last_user, 100)}")
    if last_assistant:
        parts.append(f"核心结论：{_clip(last_assistant, 140)}")
    summary = "；".join(parts)[:380]

    facts: list[str] = []
    for m in usable[-4:]:
        prefix = "用户" if m.role == "user" else "助手"
        snippet = _clip(m.content, 100)
        if snippet:
            facts.append(f"{prefix}：{snippet}")

    raw_tokens = re.findall(r"[\w\u4e00-\u9fff]{2,16}", f"{title} {first_user[:200]}")
    keywords = list(dict.fromkeys(raw_tokens))[:8]
    return summary or (title or "旁聊"), facts[:5], keywords


def _parse_digest_json(raw: str | None) -> tuple[str, list[str], list[str]] | None:
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    summary = _clip(str(parsed.get("summary") or ""), 420)
    if not summary:
        return None
    raw_facts = parsed.get("key_facts")
    facts = [_clip(str(x), 140) for x in raw_facts if str(x).strip()][:6] if isinstance(raw_facts, list) else []
    raw_kw = parsed.get("keywords")
    keywords = [_clip(str(x), 32) for x in raw_kw if str(x).strip()][:10] if isinstance(raw_kw, list) else []
    return summary, facts, keywords


async def refresh_side_chat_digest(
    db: AsyncSession,
    conv_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    *,
    force: bool = False,
    use_llm: bool = True,
) -> ConversationDigest | None:
    """Incrementally build or update a side chat's digest with cost guardrails."""
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.kind != "side":
        return None
    if user_id is not None and conv.user_id != user_id:
        return None
    user_id = conv.user_id

    rows = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    completed = [
        m for m in rows if (m.content or "").strip() and (m.role == "user" or m.status == "completed")
    ]
    if not completed:
        return None

    existing = (
        await db.execute(
            select(ConversationDigest).where(ConversationDigest.conversation_id == conv.id)
        )
    ).scalar_one_or_none()

    latest_msg = completed[-1]
    if existing is not None and not force:
        if existing.last_message_id == latest_msg.id and existing.title == conv.title:
            return existing
        new_count = max(0, len(completed) - int(existing.message_count or 0))
        elapsed = (
            (datetime.now(timezone.utc) - existing.updated_at).total_seconds()
            if existing.updated_at is not None
            else DIGEST_MIN_INTERVAL_SECONDS + 1
        )
        if new_count < DIGEST_MIN_NEW_MESSAGES and elapsed < DIGEST_MIN_INTERVAL_SECONDS:
            return existing

    # Determine incremental slice since last_message_id
    delta_msgs = completed
    if existing is not None and existing.last_message_id is not None:
        cursor_idx = next(
            (idx for idx, m in enumerate(completed) if m.id == existing.last_message_id),
            None,
        )
        if cursor_idx is not None and cursor_idx + 1 < len(completed):
            delta_msgs = completed[cursor_idx + 1 :]

    summary_val: str
    facts_val: list[str]
    keywords_val: list[str]

    llm_parsed = None
    if use_llm:
        transcript_lines: list[str] = []
        for m in delta_msgs[-12:]:
            speaker = "用户" if m.role == "user" else "助手"
            transcript_lines.append(f"{speaker}: {_clip(m.content, 600)}")
        prev_block = (
            f"已有旧摘要：{existing.summary}\n已有要点：{json.dumps(existing.key_facts or [], ensure_ascii=False)}\n\n"
            if existing and existing.summary
            else ""
        )
        sys_prompt = (
            "你是跨会话记忆摘要器。请将旁聊对话增量浓缩为紧凑的 JSON，供主聊天助手跨会话回忆。"
            "必须保留关键结论、决定、专有名词、参数、文件名和未完成事项，去掉寒暄与冗余。"
            '严格输出单行 JSON：{"summary":"120-260字精炼摘要","key_facts":["要点1","要点2"],"keywords":["词1","词2"]}'
        )
        user_prompt = f"旁聊标题：{conv.title}\n{prev_block}新增对话内容：\n" + "\n".join(transcript_lines)
        raw = await _call_fast_llm(sys_prompt, user_prompt, max_tokens=450, temperature=0.1)
        llm_parsed = _parse_digest_json(raw)

    if llm_parsed is not None:
        summary_val, facts_val, keywords_val = llm_parsed
    else:
        summary_val, facts_val, keywords_val = _extractive_digest(conv.title, completed)

    search_text = " ".join(
        [conv.title or "", summary_val, " ".join(facts_val), " ".join(keywords_val)]
    ).strip()

    await detect_pgvector(db)
    vec: list[float] | None = None
    if embeddings.is_embedding_configured() and search_text:
        vecs = await embeddings.embed_texts([search_text[:2000]])
        vec = vecs[0] if vecs else None

    if existing is None:
        existing = ConversationDigest(
            user_id=user_id,
            conversation_id=conv.id,
        )
        db.add(existing)

    existing.title = conv.title
    existing.summary = summary_val
    existing.key_facts = facts_val
    existing.keywords = keywords_val
    existing.message_count = len(completed)
    existing.last_message_id = latest_msg.id
    existing.last_message_at = latest_msg.created_at
    existing.search_tsv = func.to_tsvector("simple", search_text)
    existing.embedding = vec
    existing.embedding_model = embeddings.current_embedding_model_tag() or None if vec is not None else None
    existing.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(existing)
    return existing


def schedule_side_chat_digest_refresh(conv_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Fire-and-forget debounced digest update after a side chat turn finishes."""

    async def _runner() -> None:
        try:
            r = get_redis()
            lock_key = f"digest:lock:{conv_id}"
            acquired = await r.set(lock_key, "1", ex=60, nx=True)
            if not acquired:
                return
            try:
                async with SessionLocal() as db:
                    await refresh_side_chat_digest(db, conv_id, user_id, force=False, use_llm=True)
            finally:
                try:
                    await r.delete(lock_key)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Background side-chat digest refresh skipped for %s: %s", conv_id, exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def backfill_missing_digests_lightweight(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 12,
) -> int:
    """Zero-LLM-cost extractive backfill for existing side chats lacking a digest."""
    subq = select(ConversationDigest.conversation_id).where(ConversationDigest.user_id == user_id)
    missing_convs = list(
        (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.user_id == user_id,
                    Conversation.kind == "side",
                    Conversation.id.notin_(subq),
                )
                .order_by(Conversation.last_message_at.desc().nullslast(), Conversation.updated_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    created = 0
    for conv in missing_convs:
        digest = await refresh_side_chat_digest(db, conv.id, user_id, force=True, use_llm=False)
        if digest is not None:
            created += 1
    return created


def normalize_working_state(raw: Any) -> dict[str, Any]:
    """Normalize structured L1 Working State with strict bounds to prevent unbounded drift."""
    data = raw if isinstance(raw, dict) else {}

    goals: list[dict[str, str]] = []
    seen_goals: set[str] = set()
    for g in data.get("active_goals") or []:
        if isinstance(g, str) and g.strip():
            title = _clip(g, 120)
            status = "in_progress"
            updated = ""
        elif isinstance(g, dict):
            title = _clip(str(g.get("title") or g.get("goal") or ""), 120)
            status = str(g.get("status") or "in_progress").strip().lower()
            updated = _clip(str(g.get("updated") or g.get("date") or ""), 24)
        else:
            continue
        if not title or status in ("completed", "done", "cancelled", "archived"):
            continue
        key = title.lower()
        if key in seen_goals:
            continue
        seen_goals.add(key)
        goals.append({"title": title, "status": status if status in ("in_progress", "blocked", "pending") else "in_progress", **({"updated": updated} if updated else {})})
        if len(goals) >= 8:
            break

    decisions: list[dict[str, str]] = []
    seen_dec: set[str] = set()
    for d in data.get("recent_decisions") or []:
        if isinstance(d, str) and d.strip():
            dec_txt = _clip(d, 160)
            date_txt = ""
            reason_txt = ""
        elif isinstance(d, dict):
            dec_txt = _clip(str(d.get("decision") or d.get("title") or ""), 160)
            date_txt = _clip(str(d.get("date") or ""), 24)
            reason_txt = _clip(str(d.get("reason") or ""), 100)
        else:
            continue
        if not dec_txt:
            continue
        key = dec_txt.lower()
        if key in seen_dec:
            continue
        seen_dec.add(key)
        item: dict[str, str] = {"decision": dec_txt}
        if date_txt:
            item["date"] = date_txt
        if reason_txt:
            item["reason"] = reason_txt
        decisions.append(item)
        if len(decisions) >= 10:
            break

    questions: list[str] = []
    seen_q: set[str] = set()
    for q in data.get("open_questions") or []:
        txt = _clip(str(q or ""), 140)
        if txt and txt.lower() not in seen_q:
            seen_q.add(txt.lower())
            questions.append(txt)
        if len(questions) >= 6:
            break

    entities: dict[str, str] = {}
    raw_ent = data.get("key_entities")
    if isinstance(raw_ent, dict):
        for k, v in raw_ent.items():
            kk = _clip(str(k or ""), 40)
            vv = _clip(str(v or ""), 120)
            if kk and vv:
                entities[kk] = vv
            if len(entities) >= 16:
                break

    return {
        "active_goals": goals,
        "recent_decisions": decisions,
        "open_questions": questions,
        "key_entities": entities,
    }


def apply_working_state_patch(current_raw: Any, patch_raw: Any) -> dict[str, Any]:
    """Apply an incremental structured patch to L1 Working State (eliminates free-text summary drift)."""
    base = normalize_working_state(current_raw)
    patch = patch_raw if isinstance(patch_raw, dict) else {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    completed_titles = {
        str(t).strip().lower()
        for t in (patch.get("completed_goals") or [])
        if str(t).strip()
    }
    resolved_questions = {
        str(q).strip().lower()
        for q in (patch.get("resolved_questions") or [])
        if str(q).strip()
    }

    # Filter out completed goals & merge added/updated goals
    next_goals = [
        g for g in base["active_goals"]
        if g["title"].lower() not in completed_titles
        and not any(ct in g["title"].lower() for ct in completed_titles if len(ct) >= 3)
    ]
    by_title = {g["title"].lower(): idx for idx, g in enumerate(next_goals)}
    for raw_g in patch.get("active_goals") or []:
        if isinstance(raw_g, str) and raw_g.strip():
            g_title = _clip(raw_g, 120)
            g_status = "in_progress"
        elif isinstance(raw_g, dict):
            g_title = _clip(str(raw_g.get("title") or raw_g.get("goal") or ""), 120)
            g_status = str(raw_g.get("status") or "in_progress").strip().lower()
        else:
            continue
        if not g_title:
            continue
        lk = g_title.lower()
        if g_status in ("completed", "done", "cancelled", "archived"):
            if lk in by_title:
                next_goals[by_title[lk]]["status"] = "completed"
            continue
        entry = {"title": g_title, "status": g_status if g_status in ("in_progress", "blocked", "pending") else "in_progress", "updated": today}
        if lk in by_title:
            next_goals[by_title[lk]] = entry
        else:
            by_title[lk] = len(next_goals)
            next_goals.append(entry)

    # Prepend newest decisions so recent ones never get evicted before stale ones
    new_decisions: list[dict[str, str]] = []
    for raw_d in patch.get("recent_decisions") or []:
        if isinstance(raw_d, str) and raw_d.strip():
            new_decisions.append({"decision": _clip(raw_d, 160), "date": today})
        elif isinstance(raw_d, dict) and str(raw_d.get("decision") or "").strip():
            item = {"decision": _clip(str(raw_d["decision"]), 160), "date": _clip(str(raw_d.get("date") or today), 24)}
            if str(raw_d.get("reason") or "").strip():
                item["reason"] = _clip(str(raw_d["reason"]), 100)
            new_decisions.append(item)
    merged_decisions = new_decisions + base["recent_decisions"]

    # Update open questions
    next_questions = [
        q for q in base["open_questions"]
        if q.lower() not in resolved_questions
        and not any(rq in q.lower() for rq in resolved_questions if len(rq) >= 3)
    ]
    for raw_q in patch.get("open_questions") or []:
        txt = _clip(str(raw_q or ""), 140)
        if txt:
            next_questions.insert(0, txt)

    # Merge key entities
    merged_entities = dict(base["key_entities"])
    if isinstance(patch.get("key_entities"), dict):
        for k, v in patch["key_entities"].items():
            kk = _clip(str(k or ""), 40)
            vv = _clip(str(v or ""), 120)
            if kk and vv:
                merged_entities[kk] = vv

    return normalize_working_state(
        {
            "active_goals": next_goals,
            "recent_decisions": merged_decisions,
            "open_questions": next_questions,
            "key_entities": merged_entities,
        }
    )


def format_working_state_prompt(
    working_state: dict[str, Any] | None,
    *,
    rolling_summary: str | None = None,
    max_chars: int = 1800,
) -> str:
    """Render structured L1 Working State into a compact, deterministic Markdown block (falls back to rolling_summary)."""
    ws = normalize_working_state(working_state) if working_state else None
    has_structured = bool(
        ws
        and (ws["active_goals"] or ws["recent_decisions"] or ws["open_questions"] or ws["key_entities"])
    )
    if not has_structured:
        legacy = (rolling_summary or "").strip()
        if len(legacy) > max_chars:
            legacy = legacy[:max_chars].rstrip() + "…"
        return legacy

    parts: list[str] = []
    if ws["active_goals"]:
        lines = ["### 进行中目标与待办"]
        for g in ws["active_goals"]:
            st_tag = "阻塞" if g["status"] == "blocked" else ("待开始" if g["status"] == "pending" else "进行中")
            dt = f" ({g['updated']})" if g.get("updated") else ""
            lines.append(f"- [{st_tag}] {g['title']}{dt}")
        parts.append("\n".join(lines))

    if ws["recent_decisions"]:
        lines = ["### 近期已拍板决策"]
        for d in ws["recent_decisions"]:
            dt = f"[{d['date']}] " if d.get("date") else ""
            reason = f"（原因：{d['reason']}）" if d.get("reason") else ""
            lines.append(f"- {dt}{d['decision']}{reason}")
        parts.append("\n".join(lines))

    if ws["open_questions"]:
        lines = ["### 待决问题"]
        for q in ws["open_questions"]:
            lines.append(f"- {q}")
        parts.append("\n".join(lines))

    if ws["key_entities"]:
        kv = "；".join(f"{k}: {v}" for k, v in ws["key_entities"].items())
        parts.append(f"### 关键实体与参数\n{kv}")

    rendered = "\n\n".join(parts)
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars].rstrip() + "…"
    return rendered


def _parse_episode_and_state_json(raw: str | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    ep = parsed.get("episode") if isinstance(parsed.get("episode"), dict) else parsed
    topic = _clip(str(ep.get("topic") or ep.get("title") or ""), 160)
    summary = _clip(str(ep.get("summary") or ""), 520)
    if not summary:
        return None
    key_facts = [_clip(str(x), 150) for x in (ep.get("key_facts") or []) if str(x).strip()][:8]
    entities = [_clip(str(x), 48) for x in (ep.get("entities") or []) if str(x).strip()][:12]
    state_patch = parsed.get("working_state_patch") if isinstance(parsed.get("working_state_patch"), dict) else {}
    return (
        {
            "topic": topic or _clip(summary, 48),
            "summary": summary,
            "key_facts": key_facts,
            "entities": entities,
        },
        state_patch,
    )


async def archive_conversation_episode_if_needed(
    db: AsyncSession,
    conv: Conversation,
    *,
    trigger_messages: int = EPISODE_TRIGGER_MESSAGES,
    trigger_tokens: int = EPISODE_TRIGGER_TOKENS,
    keep_recent: int = EPISODE_KEEP_RECENT,
    force: bool = False,
) -> ConversationEpisode | None:
    """Unified L1+L2 archival for BOTH Main Chat and long Side Chats:
    1. Seals evicted turns into an immutable `ConversationEpisode` (zero Telephone Game drift).
    2. Incrementally patches `conv.working_state` and advances `working_state_cursor_msg_id`.
    """
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    completed = [
        m for m in rows if (m.content or "").strip() and (m.role == "user" or m.status == "completed")
    ]
    if len(completed) <= keep_recent:
        return None

    cursor_id = conv.working_state_cursor_msg_id or conv.summary_cursor_msg_id
    start_idx = 0
    if cursor_id is not None:
        found = next((i for i, m in enumerate(completed) if m.id == cursor_id), None)
        if found is not None:
            start_idx = found + 1

    unarchived = completed[start_idx:]
    if len(unarchived) <= keep_recent:
        return None

    unarchived_tokens = sum(estimate_tokens(m.content) for m in unarchived)
    # Check natural time boundary (>= 4h gap between older turns and latest turns)
    time_gap_split: int | None = None
    for idx in range(EPISODE_GAP_MIN_MESSAGES, len(unarchived) - 1):
        prev_ts = unarchived[idx - 1].created_at
        cur_ts = unarchived[idx].created_at
        if prev_ts and cur_ts and (cur_ts - prev_ts).total_seconds() >= EPISODE_GAP_SECONDS:
            time_gap_split = idx

    should_trigger = (
        force
        or len(unarchived) >= trigger_messages
        or unarchived_tokens >= trigger_tokens
        or (time_gap_split is not None and time_gap_split >= EPISODE_GAP_MIN_MESSAGES)
    )
    if not should_trigger:
        return None

    if time_gap_split is not None and not (len(unarchived) >= trigger_messages or unarchived_tokens >= trigger_tokens):
        evicted = unarchived[:time_gap_split]
    else:
        evict_count = len(unarchived) - keep_recent
        # Archive in bounded chunks (<= 24 msgs per episode) so every single message is captured cleanly with zero drops!
        evicted = unarchived[: min(evict_count, 24)]

    if not evicted:
        return None

    transcript = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'} ({_format_short_date(m.created_at)}): {_clip(m.content, 650)}"
        for m in evicted
    )
    current_ws_json = json.dumps(normalize_working_state(conv.working_state), ensure_ascii=False)
    sys_prompt = (
        "你是长期对话情景归档器与工作态维护器。你需要一次性完成两件事：\n"
        "1. 将即将移出窗口的这段对话封存为一条不可变的情景卡片 `episode`（保留关键数字、决定、代码/文件名、专有名词与因果脉络）；\n"
        "2. 基于既有 `working_state`，输出结构化增量补丁 `working_state_patch`（更新进行中目标、标记已完成目标 `completed_goals`、新增近期决策、移除已解决的问题）。\n"
        "严格输出单行 JSON：\n"
        '{"episode":{"topic":"8-24字主题标题","summary":"160-320字高密度总结","key_facts":["关键事实1"],"entities":["实体/参数/文件名"]},'
        '"working_state_patch":{"active_goals":[{"title":"目标","status":"in_progress"}],"completed_goals":["已完成目标标题"],'
        '"recent_decisions":[{"decision":"决定","reason":"原因"}],"open_questions":["待决问题"],"resolved_questions":["已解决问题"],"key_entities":{"键":"值"}}}'
    )
    user_prompt = (
        f"会话类型：{'主聊天' if conv.kind == 'main' else '旁聊'}（标题：{conv.title}）\n"
        f"当前工作状态 working_state：{current_ws_json}\n\n"
        f"待封存对话片段（共 {len(evicted)} 条消息）：\n{transcript}"
    )

    raw = await _call_fast_llm(sys_prompt, user_prompt, max_tokens=850, temperature=0.1, timeout_seconds=25.0)
    parsed = _parse_episode_and_state_json(raw)
    if parsed is not None:
        ep_data, state_patch = parsed
    else:
        sum_txt, facts_list, kw_list = _extractive_digest(conv.title, evicted)
        ep_data = {
            "topic": _clip(evicted[0].content, 48) or conv.title or "历史片段",
            "summary": sum_txt,
            "key_facts": facts_list,
            "entities": kw_list,
        }
        state_patch = {}

    next_index = int(
        (
            await db.scalar(
                select(func.coalesce(func.max(ConversationEpisode.episode_index), 0)).where(
                    ConversationEpisode.conversation_id == conv.id
                )
            )
        )
        or 0
    ) + 1

    await detect_pgvector(db)
    search_text = " ".join(
        [
            ep_data["topic"],
            ep_data["summary"],
            " ".join(ep_data["key_facts"]),
            " ".join(ep_data["entities"]),
        ]
    ).strip()
    vec: list[float] | None = None
    if embeddings.is_embedding_configured() and search_text:
        vecs = await embeddings.embed_texts([search_text[:2000]])
        vec = vecs[0] if vecs else None

    episode = ConversationEpisode(
        user_id=conv.user_id,
        conversation_id=conv.id,
        conversation_kind="main" if conv.kind == "main" else "side",
        episode_index=next_index,
        topic=ep_data["topic"],
        summary=ep_data["summary"],
        key_facts=ep_data["key_facts"],
        entities=ep_data["entities"],
        start_msg_id=evicted[0].id,
        end_msg_id=evicted[-1].id,
        started_at=evicted[0].created_at,
        ended_at=evicted[-1].created_at,
        message_count=len(evicted),
        token_count=sum(estimate_tokens(m.content) for m in evicted),
        search_tsv=func.to_tsvector("simple", search_text),
        embedding=vec,
        embedding_model=embeddings.current_embedding_model_tag() or None if vec is not None else None,
    )
    db.add(episode)

    now_dt = datetime.now(timezone.utc)
    next_ws = apply_working_state_patch(conv.working_state, state_patch)
    conv.working_state = next_ws
    conv.working_state_cursor_msg_id = evicted[-1].id
    conv.working_state_updated_at = now_dt
    # Keep legacy rolling_summary & cursor synchronized for full backward compatibility
    conv.rolling_summary = format_working_state_prompt(next_ws, rolling_summary=conv.rolling_summary)
    conv.summary_cursor_msg_id = evicted[-1].id
    conv.summary_updated_at = now_dt

    await db.commit()
    await db.refresh(episode)
    return episode


def schedule_episode_archive_check(conv_id: uuid.UUID) -> None:
    """Schedule durable L1 Working State + L2 Episode archival check via Redis RAG queue."""
    from app.services import rag_jobs

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(rag_jobs.enqueue_job("archive_episode", {"conversation_id": str(conv_id)}))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def load_cursor_aligned_history(
    db: AsyncSession,
    conv: Conversation,
    *,
    min_messages: int = CURSOR_HISTORY_MIN_MESSAGES,
    max_messages: int = CURSOR_HISTORY_MAX_MESSAGES,
    max_tokens: int = CURSOR_HISTORY_MAX_TOKENS,
) -> list[dict[str, str]]:
    """Load cursor-aligned verbatim history with ZERO black-hole gaps and ZERO redundant archived overlap.

    - Prefers all completed user/assistant messages strictly after `working_state_cursor_msg_id` (or `summary_cursor_msg_id`).
    - If fewer than `min_messages` exist after the cursor (e.g., right after an archive run), pads backward up to
      `min_messages` so turn continuity stays natural.
    - Enforces `max_messages` and `max_tokens` from newest backward while preserving turn ordering.
    """
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(max(max_messages + 12, 40))
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    completed = [
        m
        for m in rows
        if (m.content or "").strip()
        and (m.role == "user" or m.status not in ("failed", "cancelled", "streaming", "waiting"))
    ]
    if not completed:
        return []

    cursor_id = conv.working_state_cursor_msg_id or conv.summary_cursor_msg_id
    selected = completed
    if cursor_id is not None:
        c_idx = next((i for i, m in enumerate(completed) if m.id == cursor_id), None)
        if c_idx is not None:
            after_cursor = completed[c_idx + 1 :]
            if len(after_cursor) >= min_messages:
                selected = after_cursor
            else:
                selected = completed[-min_messages:]

    # Enforce max_messages & max_tokens from newest backward
    kept: list[Message] = []
    used_tokens = 0
    for m in reversed(selected):
        t = estimate_tokens(m.content)
        if kept and (len(kept) >= max_messages or used_tokens + t > max_tokens):
            break
        kept.append(m)
        used_tokens += t
    kept.reverse()
    return [{"role": m.role, "content": m.content} for m in kept]


def _extractive_rolling_summary(previous: str | None, evicted: list[Message]) -> str:
    lines: list[str] = []
    if previous and previous.strip():
        lines.append(previous.strip())
    for m in evicted:
        role_label = "用户" if m.role == "user" else "助手"
        snippet = _clip(m.content, 160)
        if snippet:
            lines.append(f"- {role_label}：{snippet}")
    joined = "\n".join(lines).strip()
    if len(joined) > ROLLING_SUMMARY_MAX_CHARS:
        joined = joined[-ROLLING_SUMMARY_MAX_CHARS:]
    return joined


async def compact_main_conversation_if_needed(
    db: AsyncSession,
    conv: Conversation,
    *,
    trigger_tokens: int = COMPACT_TRIGGER_TOKENS,
    trigger_messages: int = COMPACT_TRIGGER_MESSAGES,
    recent_keep: int = RECENT_VERBATIM_MESSAGES,
) -> str | None:
    """Incrementally fold older main-chat turns into ``conv.rolling_summary`` while keeping raw messages intact."""
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.created_at.asc(), Message.id.asc())
            )
        )
        .scalars()
        .all()
    )
    completed = [
        m for m in rows if (m.content or "").strip() and (m.role == "user" or m.status == "completed")
    ]
    if len(completed) <= recent_keep:
        return conv.rolling_summary

    start_idx = 0
    if conv.summary_cursor_msg_id is not None:
        found = next((i for i, m in enumerate(completed) if m.id == conv.summary_cursor_msg_id), None)
        if found is not None:
            start_idx = found + 1

    uncompacted = completed[start_idx:]
    if len(uncompacted) <= recent_keep:
        return conv.rolling_summary

    uncompacted_tokens = sum(estimate_tokens(m.content) for m in uncompacted)
    if len(uncompacted) < trigger_messages and uncompacted_tokens < trigger_tokens:
        return conv.rolling_summary

    evict_count = len(uncompacted) - recent_keep
    evicted = uncompacted[:evict_count]
    if not evicted:
        return conv.rolling_summary

    transcript = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}: {_clip(m.content, 700)}"
        for m in evicted[-30:]
    )
    sys_prompt = (
        "你是长期对话记忆压缩器。请将既有主聊天摘要与新移出窗口的历史消息增量合并，"
        "严格控制在 1500 字以内，按以下 4 个固定小节精炼输出（无内容的小节可省略）：\n"
        "### 核心事实与决策\n### 进行中的事项与待办\n### 用户明确偏好与约束\n### 关键实体、参数与时间线\n"
        "要求：严禁丢弃关键数字、名称、决定和用户纠正过的要求；不要寒暄。"
    )
    prev_summary = (conv.rolling_summary or "").strip()
    user_prompt = (
        (f"已有滚动摘要：\n{prev_summary}\n\n" if prev_summary else "")
        + f"新增需要压缩的历史消息：\n{transcript}"
    )

    merged = await _call_fast_llm(sys_prompt, user_prompt, max_tokens=1000, temperature=0.1, timeout_seconds=25.0)
    if not merged:
        merged = _extractive_rolling_summary(prev_summary, evicted)
    if len(merged) > ROLLING_SUMMARY_MAX_CHARS:
        merged = merged[:ROLLING_SUMMARY_MAX_CHARS].rstrip() + "…"

    conv.rolling_summary = merged
    conv.summary_cursor_msg_id = evicted[-1].id
    conv.summary_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return conv.rolling_summary


def schedule_main_compaction_check(conv_id: uuid.UUID) -> None:
    """Run main-chat rolling compaction asynchronously after turn completion to keep TTFT low."""

    async def _runner() -> None:
        try:
            r = get_redis()
            lock_key = f"compact:lock:{conv_id}"
            acquired = await r.set(lock_key, "1", ex=90, nx=True)
            if not acquired:
                return
            try:
                async with SessionLocal() as db:
                    conv = await db.get(Conversation, conv_id)
                    if conv is not None and conv.kind == "main":
                        await compact_main_conversation_if_needed(db, conv)
            finally:
                try:
                    await r.delete(lock_key)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Background main-chat compaction skipped for %s: %s", conv_id, exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _format_short_date(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d")


async def _recall_relevant_digests(
    db: AsyncSession,
    user_id: uuid.UUID,
    query_text: str,
    *,
    limit: int = RECALLED_MAX_ITEMS,
) -> list[ConversationDigest]:
    cleaned = (query_text or "").strip()
    if not cleaned:
        return []

    await detect_pgvector(db)
    digest_stmt = (
        select(ConversationDigest)
        .where(ConversationDigest.user_id == user_id)
        .order_by(ConversationDigest.last_message_at.desc().nullslast(), ConversationDigest.updated_at.desc())
        .limit(200)
    )
    if is_pgvector_enabled():
        digest_stmt = digest_stmt.options(defer(ConversationDigest.embedding))
    all_digests = list((await db.execute(digest_stmt)).scalars().all())
    if not all_digests:
        return []

    by_id = {d.conversation_id: d for d in all_digests}
    scores: dict[uuid.UUID, float] = {}
    rrf_k = 60

    # 1. FTS leg
    try:
        async with db.begin_nested():
            fts_rows = (
                await db.execute(
                    select(ConversationDigest.conversation_id)
                    .where(
                        ConversationDigest.user_id == user_id,
                        ConversationDigest.search_tsv.op("@@")(func.plainto_tsquery("simple", cleaned)),
                    )
                    .order_by(
                        desc(func.ts_rank_cd(ConversationDigest.search_tsv, func.plainto_tsquery("simple", cleaned)))
                    )
                    .limit(limit * 3)
                )
            ).scalars().all()
        for rank, cid in enumerate(fts_rows, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    except Exception:
        pass

    # 2. Substring / token overlap leg (works great for Chinese terms where 'simple' FTS splits on spaces)
    q_low = cleaned.lower()
    terms = [t for t in re.findall(r"[\w\u4e00-\u9fff]{2,}", q_low)][:8]
    if not terms and q_low:
        terms = [q_low]
    lexical_hits: list[tuple[int, uuid.UUID]] = []
    for d in all_digests:
        hay = f"{d.title} {d.summary} {' '.join(d.key_facts or [])} {' '.join(d.keywords or [])}".lower()
        hits = sum(1 for t in terms if t in hay)
        if q_low in hay:
            hits += 2
        if hits > 0:
            lexical_hits.append((hits, d.conversation_id))
    lexical_hits.sort(key=lambda pair: pair[0], reverse=True)
    for rank, (_, cid) in enumerate(lexical_hits[: limit * 3], 1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)

    # 3. Vector leg (pgvector HNSW with iterative_scan or in-process cosine fallback)
    if embeddings.is_embedding_configured():
        q_vecs = await embeddings.embed_texts([cleaned[:1000]])
        q_vec = q_vecs[0] if q_vecs else None
        if q_vec:
            if is_pgvector_enabled():
                try:
                    vec_lit = "[" + ",".join(f"{x:.8f}" for x in q_vec) + "]"
                    try:
                        async with db.begin_nested():
                            await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                    except Exception:
                        pass
                    async with db.begin_nested():
                        res = await db.execute(
                            text(
                                """
                                SELECT conversation_id
                                FROM conversation_digests
                                WHERE user_id = :uid
                                  AND embedding IS NOT NULL
                                  AND (embedding <=> CAST(:qvec AS vector)) < 0.78
                                ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                                LIMIT :lim
                                """
                            ),
                            {"uid": user_id, "qvec": vec_lit, "lim": limit * 3},
                        )
                        rows = res.fetchall()
                    for rank, (cid,) in enumerate(rows, 1):
                        scores[cid] = scores.get(cid, 0.0) + 1.2 / (rrf_k + rank)
                except Exception:
                    pass
            else:
                vec_scored = [
                    (_cosine_sim(q_vec, d.embedding), d.conversation_id)
                    for d in all_digests
                    if d.embedding
                ]
                vec_scored.sort(key=lambda pair: pair[0], reverse=True)
                for rank, (sim, cid) in enumerate(vec_scored[: limit * 3], 1):
                    if sim > 0.15:
                        scores[cid] = scores.get(cid, 0.0) + 1.2 / (rrf_k + rank)

    if not scores:
        return []

    # Mild recency boost (decays over 30 days)
    now = datetime.now(timezone.utc)
    for cid in list(scores.keys()):
        d = by_id.get(cid)
        if d and d.last_message_at:
            age_days = max(0.0, (now - d.last_message_at).total_seconds() / 86400.0)
            scores[cid] += 0.004 / (1.0 + age_days / 7.0)

    ranked_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:limit]
    return [by_id[cid] for cid in ranked_ids if cid in by_id]


def schedule_backfill_missing_digests(user_id: uuid.UUID, limit: int = 12) -> None:
    """Non-blocking background backfill for migrated side chats without digests."""

    async def _runner() -> None:
        try:
            async with SessionLocal() as db:
                await backfill_missing_digests_lightweight(db, user_id, limit=limit)
        except Exception as exc:
            logger.debug("Background digest backfill skipped for user=%s: %s", user_id, exc)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _is_low_signal_turn(user_content: str, assistant_content: str) -> bool:
    """Filter trivial acknowledgement turns out of message_chunks to prevent vector index noise."""
    u = (user_content or "").strip()
    a = (assistant_content or "").strip()
    if len(u) + len(a) < 40:
        return True
    u_norm = u.lower().strip("!！。.~～?？,， ")
    if u_norm in _LOW_SIGNAL_USER_MSGS and len(a) < 120 and "```" not in a:
        return True
    return False


async def index_turn_chunk(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_kind: str,
    conversation_title: str,
    user_msg_id: uuid.UUID | None,
    assistant_msg_id: uuid.UUID | None,
    user_content: str,
    assistant_content: str,
) -> MessageChunk | None:
    """Vectorize & index a substantive Q&A turn into ``message_chunks`` for verbatim episodic recall."""
    if _is_low_signal_turn(user_content, assistant_content):
        return None
    u_txt = _clip(user_content, 600)
    a_txt = _clip(assistant_content, 1000)
    if not u_txt and not a_txt:
        return None

    await detect_pgvector(db)
    dt_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    kind_label = "主聊" if conversation_kind == "main" else "旁聊"
    header = f"[{kind_label}: {conversation_title or '未命名'} | {dt_label}]"
    body = f"用户：{u_txt}\n助手：{a_txt}".strip()
    embed_text = f"{header}\n{body}"

    vec: list[float] | None = None
    if embeddings.is_embedding_configured():
        vecs = await embeddings.embed_texts([embed_text[:1800]])
        vec = vecs[0] if vecs else None

    chunk = MessageChunk(
        user_id=user_id,
        conversation_id=conversation_id,
        conversation_kind="main" if conversation_kind == "main" else "side",
        start_msg_id=user_msg_id,
        end_msg_id=assistant_msg_id,
        context_header=header,
        content=body,
        token_count=estimate_tokens(body),
        search_tsv=func.to_tsvector("simple", embed_text),
        embedding=vec,
        embedding_model=embeddings.current_embedding_model_tag() or None if vec is not None else None,
    )
    db.add(chunk)
    await db.commit()
    return chunk


def schedule_turn_chunk_indexing(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    conversation_kind: str,
    conversation_title: str,
    user_msg_id: uuid.UUID | None,
    assistant_msg_id: uuid.UUID | None,
    user_content: str,
    assistant_content: str,
) -> None:
    """Schedule durable episodic turn vectorization via Redis job queue (fallback: local task)."""
    from app.services import rag_jobs

    payload = {
        "user_id": str(user_id),
        "conversation_id": str(conversation_id),
        "conversation_kind": conversation_kind,
        "conversation_title": conversation_title,
        "user_msg_id": str(user_msg_id) if user_msg_id else None,
        "assistant_msg_id": str(assistant_msg_id) if assistant_msg_id else None,
        "user_content": user_content,
        "assistant_content": assistant_content,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(rag_jobs.enqueue_job("index_turn_chunk", payload))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _recall_relevant_message_chunks(
    db: AsyncSession,
    user_id: uuid.UUID,
    query_text: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Hybrid pgvector + pg_trgm + FTS recall over episodic ``message_chunks``."""
    cleaned = (query_text or "").strip()
    if not cleaned:
        return []
    await detect_pgvector(db)

    scores: dict[uuid.UUID, float] = {}
    records: dict[uuid.UUID, dict[str, Any]] = {}
    rrf_k = 60

    # 1. Vector HNSW leg
    if embeddings.is_embedding_configured() and is_pgvector_enabled():
        q_vecs = await embeddings.embed_texts([cleaned[:1000]])
        q_vec = q_vecs[0] if q_vecs else None
        if q_vec:
            vec_lit = "[" + ",".join(f"{x:.8f}" for x in q_vec) + "]"
            try:
                try:
                    async with db.begin_nested():
                        await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                except Exception:
                    pass
                async with db.begin_nested():
                    res = await db.execute(
                        text(
                            """
                            SELECT id, conversation_id, conversation_kind, context_header, content
                            FROM message_chunks
                            WHERE user_id = :uid
                              AND embedding IS NOT NULL
                              AND (embedding <=> CAST(:qvec AS vector)) < 0.72
                            ORDER BY embedding <=> CAST(:qvec AS vector) ASC
                            LIMIT :lim
                            """
                        ),
                        {"uid": user_id, "qvec": vec_lit, "lim": limit * 3},
                    )
                    vec_rows = res.fetchall()
                for rank, row in enumerate(vec_rows, 1):
                    cid = row[0]
                    scores[cid] = scores.get(cid, 0.0) + 1.25 / (rrf_k + rank)
                    records.setdefault(
                        cid,
                        {
                            "conversation_id": str(row[1]),
                            "kind": str(row[2] or "side"),
                            "context_header": str(row[3] or ""),
                            "content": str(row[4] or ""),
                        },
                    )
            except Exception:
                pass

    # 2. pg_trgm CJK leg
    if len(cleaned) >= 2:
        try:
            async with db.begin_nested():
                res = await db.execute(
                    text(
                        """
                        SELECT id, conversation_id, conversation_kind, context_header, content
                        FROM message_chunks
                        WHERE user_id = :uid AND word_similarity(:q, content) >= 0.18
                        ORDER BY word_similarity(:q, content) DESC, created_at DESC
                        LIMIT :lim
                        """
                    ),
                    {"uid": user_id, "q": cleaned, "lim": limit * 3},
                )
                trgm_rows = res.fetchall()
            for rank, row in enumerate(trgm_rows, 1):
                cid = row[0]
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
                records.setdefault(
                    cid,
                    {
                        "conversation_id": str(row[1]),
                        "kind": str(row[2] or "side"),
                        "context_header": str(row[3] or ""),
                        "content": str(row[4] or ""),
                    },
                )
        except Exception:
            pass

    # 3. FTS leg
    try:
        async with db.begin_nested():
            res = await db.execute(
                text(
                    """
                    SELECT id, conversation_id, conversation_kind, context_header, content
                    FROM message_chunks
                    WHERE user_id = :uid AND search_tsv @@ plainto_tsquery('simple', :q)
                    ORDER BY ts_rank_cd(search_tsv, plainto_tsquery('simple', :q)) DESC
                    LIMIT :lim
                    """
                ),
                {"uid": user_id, "q": cleaned, "lim": limit * 3},
            )
            fts_rows = res.fetchall()
        for rank, row in enumerate(fts_rows, 1):
            cid = row[0]
            scores[cid] = scores.get(cid, 0.0) + 0.9 / (rrf_k + rank)
            records.setdefault(
                cid,
                {
                    "conversation_id": str(row[1]),
                    "kind": str(row[2] or "side"),
                    "context_header": str(row[3] or ""),
                    "content": str(row[4] or ""),
                },
            )
    except Exception:
        pass

    ranked = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)[:limit]
    return [records[cid] for cid in ranked]


async def build_main_chat_memory_context(
    db: AsyncSession,
    user: User,
    conv: Conversation,
    query_text: str,
    *,
    max_recent_dir: int = DIRECTORY_MAX_ITEMS,
    max_recalled: int = RECALLED_MAX_ITEMS,
) -> dict[str, str]:
    """Assemble lightweight L1 Working State + Recent Active Side-Chat Directory (ZERO duplicate RAG RTT).

    Deep semantic/hybrid retrieval across side-chat digests, main-chat episodes, and message chunks is
    executed ONCE by Agent's `UnifiedKnowledgeRetriever` (`rag_prefetch` + `knowledge_search`) with `[S1..Sn]` citations.
    """
    schedule_backfill_missing_digests(user.id, limit=12)

    await detect_pgvector(db)
    recent_stmt = (
        select(ConversationDigest)
        .where(ConversationDigest.user_id == user.id)
        .order_by(ConversationDigest.last_message_at.desc().nullslast(), ConversationDigest.updated_at.desc())
        .limit(max_recent_dir)
    )
    if is_pgvector_enabled():
        recent_stmt = recent_stmt.options(defer(ConversationDigest.embedding))
    recent_digests = list((await db.execute(recent_stmt)).scalars().all())

    cross_chat_context = ""
    if recent_digests:
        dir_lines = [
            "近期活跃旁聊目录（仅标题与近况速览；涉及深层细节、参数或早期主聊记录请直接参考本轮预召回证据或调用 `knowledge_search` / `read_conversation_history`）："
        ]
        used = 0
        for d in recent_digests:
            dt_str = _format_short_date(d.last_message_at or d.updated_at)
            line = f"- [{dt_str}] 「{d.title}」(conv_id=`{d.conversation_id}`): {_clip(d.summary, 110)}"
            if used + len(line) > DIRECTORY_MAX_CHARS:
                break
            dir_lines.append(line)
            used += len(line)
        cross_chat_context = "\n".join(dir_lines)

    working_state_block = format_working_state_prompt(
        conv.working_state,
        rolling_summary=conv.rolling_summary,
    )

    return {
        "rolling_summary": working_state_block,
        "working_state_prompt": working_state_block,
        "cross_chat_context": cross_chat_context,
    }
