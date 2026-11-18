import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ConversationFileOut
from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.models import Conversation, ConversationFile, Message, User
from app.db.session import SessionLocal
from app.services import cos, membership, memory_service, provisioning, skills_service, titles, usage
from app.services.hermes import HermesClient, HermesError

logger = logging.getLogger("whitz.chat")

TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}
TERMINAL_STATUSES = {
    "completed": "run.completed",
    "failed": "run.failed",
    "cancelled": "run.cancelled",
    "interrupted": "run.interrupted",
}
ROLE_ORDER = {"user": 0, "assistant": 1, "tool": 2}


def sse(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


def sort_messages(messages: list[Message]) -> list[Message]:
    return sorted(messages, key=lambda m: (m.created_at, ROLE_ORDER.get(m.role, 3), str(m.id)))


def _history_from_messages(messages: list[Message]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for msg in messages:
        if msg.role not in ("user", "assistant"):
            continue
        text = (msg.content or "").strip()
        if not text:
            continue
        if msg.role == "assistant" and msg.status in ("failed", "cancelled", "streaming", "waiting"):
            continue
        history.append({"role": msg.role, "content": msg.content})
    return history


async def _settle_usage(db: AsyncSession, user_id: uuid.UUID, assistant: Message) -> None:
    """Record dashboard usage and deduct credits once per assistant message."""
    tokens = usage.tokens_from_usage((assistant.tool_payload or {}).get("usage"))
    if tokens > 0:
        await usage.record_tokens(db, user_id, tokens)
        await membership.settle(
            db,
            user_id,
            tokens,
            message_id=assistant.id,
            conversation_id=assistant.conversation_id,
        )
    elif assistant.status == "completed":
        logger.warning("run completed without token usage message=%s", assistant.id)


def _normalize_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "content": item.get("content") or item.get("title") or item.get("text") or item.get("task") or "",
        "status": item.get("status") or "pending",
        "parent": item.get("parent"),
    }


def _find_todos(obj) -> list[dict] | None:
    """Recursively locate a list of todo-like dicts (id/content/status)."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any(
            ("status" in x and any(k in x for k in ("content", "title", "text", "task"))) for x in obj
        ):
            return [_normalize_item(x) for x in obj]
        for x in obj:
            found = _find_todos(x)
            if found is not None:
                return found
    elif isinstance(obj, dict):
        for key in ("todos", "items", "tasks", "plan", "steps"):
            if key in obj:
                found = _find_todos(obj[key])
                if found is not None:
                    return found
        for v in obj.values():
            found = _find_todos(v)
            if found is not None:
                return found
    return None


def parse_todos(preview) -> list[dict] | None:
    if preview is None:
        return None
    if isinstance(preview, (list, dict)):
        return _find_todos(preview)
    if isinstance(preview, str):
        try:
            return _find_todos(json.loads(preview))
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _is_write_workspace_tool(tool_name: str) -> bool:
    cleaned = (tool_name or "").strip().lower()
    return cleaned == "write_workspace_file" or cleaned.endswith("write_workspace_file")


def _extract_artifact_file_id(preview: Any) -> uuid.UUID | None:
    obj: Any = None
    if isinstance(preview, dict):
        obj = preview
    elif isinstance(preview, str):
        raw = ChatPipeline._unwrap_tool_result(preview)
        start = raw.find("{")
        if start >= 0:
            try:
                obj = json.loads(raw[start:])
            except (json.JSONDecodeError, ValueError):
                obj = None
    if not isinstance(obj, dict):
        return None
    raw_id = obj.get("file_id") or obj.get("id")
    if not raw_id:
        return None
    try:
        return uuid.UUID(str(raw_id))
    except (TypeError, ValueError):
        return None


class ChatPipeline:
    def __init__(
        self,
        db: AsyncSession,
        client: HermesClient,
        conv: Conversation,
        assistant: Message,
        run_id: str,
        started_at: float | None = None,
        max_seconds: int | None = None,
    ):
        self.db = db
        self.client = client
        self.conv = conv
        self.assistant = assistant
        self.run_id = run_id
        self.max_seconds = max_seconds
        self.buffer: list[str] = []
        self.last_flush = time.monotonic()
        self.pending_tools: dict[str, list[Message]] = {}
        self.existing_tools: dict[str, list[Message]] = {}
        self.plan: dict | None = conv.plan
        if not self.plan:
            stored_plan = (assistant.tool_payload or {}).get("plan")
            if isinstance(stored_plan, dict):
                self.plan = stored_plan
        stored = (assistant.tool_payload or {}).get("reasoning")
        self.reasoning: list[dict] = [b for b in stored if isinstance(b, dict)] if isinstance(stored, list) else []
        stored_artifacts = (assistant.tool_payload or {}).get("artifacts")
        self.artifacts: list[dict] = (
            [dict(a) for a in stored_artifacts if isinstance(a, dict)]
            if isinstance(stored_artifacts, list)
            else []
        )
        for art in self.artifacts:
            fid = art.get("id") or art.get("file_id")
            if fid:
                fid_str = str(fid)
                art.setdefault("id", fid_str)
                art.setdefault("file_id", fid_str)
        self.seen_artifact_ids: set[str] = {
            str(a.get("id") or a.get("file_id"))
            for a in self.artifacts
            if a.get("id") or a.get("file_id")
        }
        self.native_reasoning = False
        self.terminal = False
        if started_at is not None:
            self.started_at = started_at
        elif assistant.created_at is not None:
            self.started_at = assistant.created_at.timestamp() - 5
        else:
            self.started_at = 0.0
        self.run_started_dt = (
            datetime.fromtimestamp(self.started_at, tz=timezone.utc)
            if self.started_at
            else datetime.now(timezone.utc) - timedelta(seconds=5)
        )

    @staticmethod
    def _tool_key(tool: str, args) -> str:
        return f"{tool}\x00{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"

    async def prepare(self) -> None:
        if not self.assistant.hermes_run_id:
            return
        result = await self.db.execute(
            select(Message)
            .where(
                Message.conversation_id == self.conv.id,
                Message.hermes_run_id == self.run_id,
                Message.role == "tool",
            )
            .order_by(Message.created_at)
        )
        for row in result.scalars():
            args = (row.tool_payload or {}).get("args")
            key = self._tool_key(row.tool_name or "tool", args)
            self.existing_tools.setdefault(key, []).append(row)

    async def _flush(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last_flush >= 0.5:
            self.assistant.content = "".join(self.buffer)
            payload = dict(self.assistant.tool_payload or {})
            if self.reasoning:
                payload["reasoning"] = self.reasoning
            if self.plan:
                payload["plan"] = self.plan
            if self.artifacts:
                payload["artifacts"] = self.artifacts
            self.assistant.tool_payload = payload
            await self.db.commit()
            self.last_flush = now

    async def _collect_new_artifacts(self, target_file_id: uuid.UUID | None = None) -> list[dict]:
        conditions = [
            and_(
                ConversationFile.message_id.is_(None),
                or_(
                    ConversationFile.created_at >= self.run_started_dt,
                    ConversationFile.updated_at >= self.run_started_dt,
                ),
            )
        ]
        if target_file_id is not None:
            conditions.append(ConversationFile.id == target_file_id)

        rows = (
            await self.db.execute(
                select(ConversationFile)
                .where(
                    ConversationFile.conversation_id == self.conv.id,
                    ConversationFile.user_id == self.conv.user_id,
                    ConversationFile.source == "assistant",
                    ConversationFile.status == "ready",
                    or_(*conditions),
                )
                .order_by(ConversationFile.created_at.asc())
            )
        ).scalars().all()

        settings = get_settings()
        emitted: list[dict] = []
        changed = False
        for row in rows:
            fid_str = str(row.id)
            if row.message_id is None:
                row.message_id = self.assistant.id
                changed = True
            if fid_str in self.seen_artifact_ids:
                continue
            self.seen_artifact_ids.add(fid_str)
            meta = {
                "id": fid_str,
                "file_id": fid_str,
                "conversation_id": str(row.conversation_id) if row.conversation_id else str(self.conv.id),
                "filename": row.filename,
                "ext": row.ext,
                "category": row.category,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "source": row.source,
                "is_global": bool(row.is_global),
                "message_id": str(row.message_id) if row.message_id else str(self.assistant.id),
            }
            self.artifacts.append(meta)
            changed = True

            event_payload = dict(meta)
            file_out = ConversationFileOut.model_validate(row).model_dump(mode="json")
            if settings.cos_configured and row.storage_key:
                try:
                    urls = cos.presign_preview_urls(row.storage_key, row.filename, row.category, settings=settings)
                    expires_iso = (
                        datetime.now(timezone.utc) + timedelta(seconds=urls["expires_in"])
                    ).isoformat()
                    event_payload["preview_url"] = urls["preview_url"]
                    event_payload["thumb_url"] = urls["thumb_url"]
                    event_payload["preview_expires_at"] = expires_iso
                    file_out["preview_url"] = urls["preview_url"]
                    file_out["thumb_url"] = urls["thumb_url"]
                    file_out["preview_expires_at"] = expires_iso
                except cos.CosError:
                    pass
            event_payload["file"] = file_out
            emitted.append(event_payload)

        if changed:
            payload = dict(self.assistant.tool_payload or {})
            payload["artifacts"] = self.artifacts
            self.assistant.tool_payload = payload
            await self.db.commit()
        return emitted

    def _current_step(self) -> dict | None:
        items = (self.plan or {}).get("items") or []
        for idx, item in enumerate(items):
            if item.get("status") == "in_progress":
                return {
                    "index": idx + 1,
                    "total": len(items),
                    "title": item.get("content") or "",
                    "id": item.get("id"),
                }
        return None

    def _reasoning_block(self) -> dict:
        step = self._current_step()
        key = step["index"] if step else None
        if self.reasoning and self.reasoning[-1].get("step") == key:
            return self.reasoning[-1]
        block = {
            "step": key,
            "step_id": str(step["id"]) if step and step.get("id") is not None else None,
            "title": step["title"] if step else "",
            "text": "",
            "content": "",
            "tools": [],
        }
        self.reasoning.append(block)
        return block

    def _add_commentary(self, text: str) -> dict:
        block = self._reasoning_block()
        existing = block.get("content") or ""
        if text not in existing:
            block["content"] = f"{existing}\n\n{text}".strip() if existing else text
        return block

    def _take_streamed(self, text: str) -> None:
        joined = "".join(self.buffer).rstrip()
        if joined.endswith(text):
            rest = joined[: -len(text)].rstrip()
            self.buffer = [rest] if rest else []

    @staticmethod
    def _clip(value, limit: int = 2000) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                text = str(value)
        text = text.strip()
        return text if len(text) <= limit else text[:limit] + "…"

    @classmethod
    def _tool_entries(cls, tool_calls) -> list[tuple[str | None, str, str]]:
        entries: list[tuple[str | None, str, str]] = []
        for call in tool_calls or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = fn.get("name") or call.get("name") or "tool"
            args = fn.get("arguments", call.get("arguments"))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, ValueError):
                    pass
            if name == "tool_call" and isinstance(args, dict) and isinstance(args.get("calls"), list):
                for inner in args["calls"]:
                    if not isinstance(inner, dict):
                        continue
                    inner_args = inner.get("arguments")
                    if isinstance(inner_args, str):
                        try:
                            inner_args = json.loads(inner_args)
                        except (json.JSONDecodeError, ValueError):
                            pass
                    entries.append((call.get("id"), inner.get("name") or "tool", cls._clip(inner_args)))
                continue
            entries.append((call.get("id"), name, cls._clip(args)))
        return entries

    @staticmethod
    def _unwrap_tool_result(text: str) -> str:
        text = text.strip()
        text = text.removeprefix("<untrusted_tool_result")
        if text.startswith(">"):
            text = text.split(">", 1)[1]
        suffix = "</untrusted_tool_result>"
        if text.rstrip().endswith(suffix):
            text = text.rstrip()[: -len(suffix)]
        return text.strip()

    @classmethod
    def _compact_result(cls, tool_name: str, content) -> str:
        if content is None:
            return ""
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if tool_name == "todo_list":
            return "已更新任务清单"
        raw = cls._unwrap_tool_result(text)
        obj = None
        start = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0], default=-1)
        if start >= 0:
            try:
                obj = json.loads(raw[start:])
            except (json.JSONDecodeError, ValueError):
                obj = None
        if tool_name in ("web_search", "web_extract") and isinstance(obj, dict):
            data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
            items = data.get("web") or data.get("results") or data.get("items") or []
            results = []
            for item in items[:8] if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                results.append(
                    {
                        "title": str(item.get("title") or item.get("name") or "")[:200],
                        "url": str(item.get("url") or item.get("link") or "")[:500],
                        "snippet": str(
                            item.get("description") or item.get("snippet") or item.get("content") or ""
                        )[:600],
                    }
                )
            return json.dumps({"results": results}, ensure_ascii=False)
        if isinstance(obj, (dict, list)):
            return cls._clip(json.dumps(obj, ensure_ascii=False, indent=2), 4000)
        return cls._clip(raw, 1200)

    async def _persist_reasoning(self) -> None:
        if not self.reasoning and not self.plan and not self.artifacts:
            return
        payload = dict(self.assistant.tool_payload or {})
        if self.reasoning:
            payload["reasoning"] = self.reasoning
        if self.plan:
            payload["plan"] = self.plan
        if self.artifacts:
            payload["artifacts"] = self.artifacts
        self.assistant.tool_payload = payload
        await self.db.commit()

    async def _clear_active(self) -> None:
        self.conv.active_run_id = None
        self.conv.active_run_status = None
        self.conv.last_message_at = datetime.now(timezone.utc)

    async def _fetch_session(self) -> list | None:
        if not self.conv.hermes_session_id:
            return None
        try:
            return await self.client.session_messages(self.conv.hermes_session_id)
        except HermesError:
            return None

    def _plan_from_messages(self, messages: list) -> list[dict] | None:
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            try:
                ts = float(msg.get("timestamp") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts and ts < self.started_at:
                continue
            found = parse_todos(msg.get("content")) if msg.get("role") == "tool" else None
            if found is None:
                found = _find_todos(msg)
            if found is not None:
                return found
        return None

    def _reasoning_from_messages(self, messages: list) -> list[dict]:
        todos: list[dict] | None = None
        blocks: list[dict] = []
        pending: dict[str, list[dict]] = {}
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in ("assistant", "tool"):
                continue
            try:
                ts = float(msg.get("timestamp") or 0)
            except (TypeError, ValueError):
                ts = 0.0
            if ts and ts < self.started_at:
                continue
            if role == "tool":
                found = parse_todos(msg.get("content"))
                if found is not None:
                    todos = found
                call_id = msg.get("tool_call_id")
                if call_id:
                    for tool in pending.pop(call_id, []):
                        tool["result"] = self._compact_result(tool.get("name") or "", msg.get("content"))
                        tool["status"] = "completed"
                continue

            text = msg.get("reasoning_content") or msg.get("reasoning") or ""
            text = text.strip() if isinstance(text, str) else ""
            content = msg.get("content") if isinstance(msg.get("content"), str) else ""
            content = content.strip()
            entries = self._tool_entries(msg.get("tool_calls"))
            if not text and not entries:
                continue

            step = None
            step_id = None
            if todos:
                for idx, item in enumerate(todos):
                    if item.get("status") == "in_progress":
                        step = idx + 1
                        step_id = str(item.get("id")) if item.get("id") is not None else None
                        title = item.get("content") or ""
                        break
                else:
                    title = "总结" if not entries else ""
            else:
                title = "" if entries else "总结"

            block = {
                "step": step,
                "step_id": step_id,
                "title": title,
                "text": text,
                "content": content if entries else "",
                "tools": [],
            }
            for call_id, name, args in entries:
                tool = {"name": name, "args": args}
                block["tools"].append(tool)
                if call_id:
                    pending.setdefault(call_id, []).append(tool)
            blocks.append(block)
        return blocks

    def _apply_session(self, messages: list) -> None:
        items = self._plan_from_messages(messages)
        if items is not None:
            self.plan = {"items": items}
        full = self._reasoning_from_messages(messages)
        if full:
            self.reasoning = full

    async def _sync_session(self) -> AsyncIterator[dict]:
        messages = await self._fetch_session()
        if messages is None:
            return
        items = self._plan_from_messages(messages)
        plan_changed = items is not None and items != (self.plan or {}).get("items")
        if plan_changed:
            self.plan = {"items": items}
            self.conv.plan = self.plan
        before = json.dumps(self.reasoning, ensure_ascii=False, sort_keys=True)
        full = self._reasoning_from_messages(messages)
        reasoning_changed = bool(full) and json.dumps(full, ensure_ascii=False, sort_keys=True) != before
        if reasoning_changed:
            self.reasoning = full
        if reasoning_changed or plan_changed:
            await self._persist_reasoning()
        if plan_changed:
            yield sse("plan.updated", self.plan)
        if reasoning_changed:
            yield sse("reasoning.sync", {"blocks": self.reasoning})

    async def _control_ids(self, payload: dict) -> tuple[str | None, int | None]:
        request_id = payload.get("request_id") or payload.get("prompt_id")
        generation = payload.get("execution_generation")
        if request_id is None or generation is None:
            try:
                run = await self.client.get_run(self.run_id)
                controls = run.get("pending_controls") or []
                if controls:
                    request_id = request_id or controls[0].get("prompt_id") or controls[0].get("request_id")
                    generation = generation if generation is not None else controls[0].get("execution_generation")
            except HermesError:
                pass
        return request_id, generation

    async def handle(self, name: str, payload: dict) -> AsyncIterator[dict]:
        if name in ("reasoning.delta", "thinking.delta"):
            text = payload.get("delta") or payload.get("text") or ""
            if text:
                self.native_reasoning = True
                block = self._reasoning_block()
                block["text"] += text
                await self._flush()
                yield sse(
                    "reasoning.delta",
                    {"text": text, "step": block.get("step"), "title": block.get("title")},
                )

        elif name == "reasoning.available":
            text = payload.get("text") or ""
            if text and not self.native_reasoning:
                block = self._reasoning_block()
                block["text"] = (block["text"] + "\n\n" + text).strip() if block["text"] else text
                await self._persist_reasoning()
                yield sse(
                    "reasoning.block",
                    {"text": block["text"], "step": block.get("step"), "title": block.get("title")},
                )

        elif name == "message.delta":
            text = payload.get("delta") or payload.get("text") or ""
            if text:
                self.buffer.append(text)
                yield sse("message.delta", {"text": text})
                await self._flush()

        elif name == "message.interim":
            text = payload.get("text") or payload.get("delta") or ""
            text = text.strip() if isinstance(text, str) else ""
            if not text:
                yield sse("message.interim", payload)
            else:
                block = self._add_commentary(text)
                streamed = bool(payload.get("already_streamed"))
                if streamed:
                    self._take_streamed(text)
                await self._flush(force=True)
                yield sse(
                    "commentary",
                    {
                        "text": text,
                        "step": block.get("step"),
                        "title": block.get("title"),
                        "already_streamed": streamed,
                    },
                )

        elif name == "tool.started":
            streamed_text = "".join(self.buffer).strip()
            if streamed_text:
                block = self._add_commentary(streamed_text)
                self.buffer = []
                await self._flush(force=True)
                yield sse(
                    "commentary",
                    {
                        "text": streamed_text,
                        "step": block.get("step"),
                        "title": block.get("title"),
                        "already_streamed": True,
                    },
                )
            tool = payload.get("tool") or "tool"
            preview = payload.get("preview")
            key = self._tool_key(tool, preview)
            reused = self.existing_tools.get(key)
            if reused:
                row = reused.pop(0)
                row.status = "running"
                row.tool_payload = {**(row.tool_payload or {}), "status": "running"}
            else:
                row = Message(
                    conversation_id=self.conv.id,
                    role="tool",
                    tool_name=tool,
                    tool_payload={"args": preview, "status": "running"},
                    status="running",
                    hermes_run_id=self.run_id,
                )
                self.db.add(row)
            await self.db.commit()
            self.pending_tools.setdefault(tool, []).append(row)
            yield sse("tool.started", {"tool": tool, "preview": preview, "message_id": str(row.id)})
            if tool == "todo_list":
                items = parse_todos(preview)
                if items is not None:
                    self.plan = {"items": items}
                    self.conv.plan = self.plan
                    await self.db.commit()
                    yield sse("plan.updated", self.plan)

        elif name == "tool.completed":
            tool = payload.get("tool") or "tool"
            preview = payload.get("preview")
            error = payload.get("error")
            duration = payload.get("duration")
            rows = self.pending_tools.get(tool) or []
            row = rows.pop() if rows else None
            if row is not None:
                args = (row.tool_payload or {}).get("args")
                row.tool_payload = {
                    "args": args,
                    "result": preview,
                    "duration": duration,
                    "error": error,
                    "status": "failed" if error else "completed",
                }
                row.status = "failed" if error else "completed"
                await self.db.commit()
            yield sse(
                "tool.completed",
                {
                    "tool": tool,
                    "preview": preview,
                    "error": error,
                    "duration": duration,
                    "message_id": str(row.id) if row else None,
                },
            )
            if tool == "todo_list":
                items = parse_todos(preview)
                if items is not None:
                    self.plan = {"items": items}
                    self.conv.plan = self.plan
                    await self.db.commit()
                    yield sse("plan.updated", self.plan)
            if not error and _is_write_workspace_tool(tool):
                parsed_fid = _extract_artifact_file_id(preview)
                for art in await self._collect_new_artifacts(parsed_fid):
                    yield sse("workspace.file_created", art)
            async for ev in self._sync_session():
                yield ev

        elif name in ("approval.request", "clarify.request"):
            request_id, generation = await self._control_ids(payload)
            self.assistant.status = "waiting"
            self.conv.active_run_status = "waiting_for_approval" if name == "approval.request" else "waiting_for_clarify"
            await self.db.commit()
            yield sse(
                name,
                {
                    "request_id": request_id,
                    "execution_generation": generation,
                    "tool": payload.get("tool"),
                    "preview": payload.get("preview"),
                    "detail": payload,
                },
            )

        elif name == "run.completed":
            self.terminal = True
            for art in await self._collect_new_artifacts():
                yield sse("workspace.file_created", art)
            output = payload.get("output")
            self.assistant.content = output if output else "".join(self.buffer)
            self.assistant.status = "completed"
            messages = await self._fetch_session()
            if messages is not None:
                self._apply_session(messages)
            extra = dict(self.assistant.tool_payload or {})
            extra.update({"usage": payload.get("usage"), "runtime": payload.get("runtime")})
            if self.reasoning:
                extra["reasoning"] = self.reasoning
            if self.plan:
                extra["plan"] = self.plan
            if self.artifacts:
                extra["artifacts"] = self.artifacts
            self.assistant.tool_payload = extra
            self.conv.plan = self.plan
            await self._clear_active()
            await self.db.commit()
            yield sse(
                "run.completed",
                {
                    "output": self.assistant.content,
                    "usage": payload.get("usage"),
                    "plan": self.plan,
                    "reasoning": self.reasoning or None,
                    "artifacts": self.artifacts or None,
                },
            )

        elif name in ("run.failed", "run.cancelled", "run.interrupted"):
            self.terminal = True
            error = payload.get("error")
            if isinstance(error, dict):
                error = error.get("message") or json.dumps(error, ensure_ascii=False)
            self.assistant.content = payload.get("output") or "".join(self.buffer)
            self.assistant.status = "failed" if name == "run.failed" else "cancelled"
            messages = await self._fetch_session()
            if messages is not None:
                self._apply_session(messages)
            extra = dict(self.assistant.tool_payload or {})
            for key in ("usage", "runtime"):
                if payload.get(key) is not None:
                    extra[key] = payload.get(key)
            if self.reasoning:
                extra["reasoning"] = self.reasoning
            if self.plan:
                extra["plan"] = self.plan
            if self.artifacts:
                extra["artifacts"] = self.artifacts
            self.assistant.tool_payload = extra
            await self._clear_active()
            await self.db.commit()
            yield sse(
                name,
                {"error": error, "output": self.assistant.content, "plan": self.plan, "reasoning": self.reasoning or None},
            )

        else:
            yield sse(name, payload)

    async def _run_state(self) -> tuple[str, dict] | None:
        try:
            run = await self.client.get_run(self.run_id)
        except HermesError:
            return None
        return str(run.get("status") or ""), run

    async def _abort_timeout(self) -> None:
        self.terminal = True
        self.assistant.content = "".join(self.buffer)
        self.assistant.status = "failed"
        try:
            await asyncio.wait_for(self.client.stop_run(self.run_id), timeout=10)
        except (HermesError, asyncio.TimeoutError):
            pass
        await self._clear_active()
        await self.db.commit()

    async def pump(self) -> AsyncIterator[dict]:
        settings = get_settings()
        max_seconds = self.max_seconds or settings.run_max_seconds
        deadline = time.monotonic() + max_seconds
        timed_out = False
        try:
            async with asyncio.timeout(max(1.0, deadline - time.monotonic())):
                async for name, payload in self.client.stream_run_events(self.run_id):
                    async for ev in self.handle(name, payload):
                        yield ev
                    if self.terminal:
                        break
        except TimeoutError:
            timed_out = True
        except HermesError as exc:
            if exc.status_code != 404:
                raise
        if self.terminal:
            return
        if timed_out:
            await self._abort_timeout()
            yield sse(
                "run.failed",
                {
                    "error": "运行超过时长上限，已终止",
                    "output": self.assistant.content,
                    "plan": self.plan,
                    "reasoning": self.reasoning or None,
                },
            )
            return

        # Event replay expired or the stream closed early: reconcile via run status.
        while time.monotonic() < deadline:
            state = await self._run_state()
            if state is None:
                self.assistant.status = "failed"
                await self._clear_active()
                await self.db.commit()
                yield sse("error", {"code": "run_lost", "detail": "运行记录已过期，请重新发送消息"})
                return
            run_status, run = state
            event_name = TERMINAL_STATUSES.get(run_status)
            if event_name:
                payload = {
                    key: run.get(key)
                    for key in ("output", "usage", "runtime", "error", "completed", "partial", "interrupted")
                    if key in run
                }
                async for ev in self.handle(event_name, payload):
                    yield ev
                return
            yield sse("run.polling", {"run_id": self.run_id, "status": run_status})
            await asyncio.sleep(2)

        await self._abort_timeout()
        yield sse(
            "run.failed",
            {
                "error": "运行超过时长上限，已终止",
                "output": self.assistant.content,
                "plan": self.plan,
                "reasoning": self.reasoning or None,
            },
        )


async def _auto_title_events(
    db: AsyncSession,
    conv: Conversation,
    assistant: Message | None,
    client: HermesClient,
) -> AsyncIterator[dict]:
    if conv.title != "新对话" or assistant is None or assistant.status != "completed":
        return
    content = (assistant.content or "").strip()
    if not content:
        return
    first_assistant = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "assistant")
            .order_by(Message.created_at)
            .limit(1)
        )
    ).scalars().first()
    if first_assistant is None or first_assistant.id != assistant.id:
        return
    user_msg = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.created_at)
            .limit(1)
        )
    ).scalars().first()
    if user_msg is None or not (user_msg.content or "").strip():
        return

    r = get_redis()
    lock_key = f"title:inflight:{conv.id}"
    acquired = await r.set(lock_key, "1", ex=60, nx=True)
    if not acquired:
        return
    try:
        prompt = titles.build_auto_prompt(user_msg.content, content)
        title = await asyncio.wait_for(titles.complete_title(prompt), timeout=20)
        await db.refresh(conv)
        if conv.title != "新对话":
            return
        conv.title = title
        await db.commit()
        if conv.hermes_session_id:
            try:
                await client.patch_session(conv.hermes_session_id, title)
            except HermesError:
                pass
        yield sse("title.updated", {"conversation_id": str(conv.id), "title": title})
    except (asyncio.TimeoutError, titles.TitleServiceError):
        logger.warning("auto title skipped for conversation %s", conv.id)
    except Exception:
        logger.exception("auto title failed")
    finally:
        try:
            await r.delete(lock_key)
        except Exception:
            pass


def _build_workspace_instructions(
    conv_id: uuid.UUID,
    workspace_files: list[ConversationFile],
    attached_ids: set[uuid.UUID],
) -> str | None:
    if not workspace_files:
        return None
    lines = [
        f"当前对话文件工作区（conversation_id: {conv_id}）共有 {len(workspace_files)} 个已就绪文件：",
    ]
    for f in workspace_files:
        tags: list[str] = []
        if f.id in attached_ids:
            tags.append("本轮新附带")
        if f.is_global and f.conversation_id != conv_id:
            tags.append("全局共享文件")
        tag_str = f" [{' · '.join(tags)}]" if tags else ""
        lines.append(
            f"- {f.filename}{tag_str} (file_id={f.id}, category={f.category}, mime={f.mime_type}, size={f.size_bytes} bytes)"
        )
    lines.append(
        "若用户询问或需要处理以上任意文件，请调用 list_workspace_files / read_workspace_file / search_workspace_files 工具按需读取真实内容；若需要向用户交付报告、代码、网页、表格等文本产物，可调用 write_workspace_file 写入工作区。"
    )
    return "\n".join(lines)


def _serialize_pending_item(item: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in item.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _pending_events_since(
    profile: str,
    initial_mem_ids: set[str] | None = None,
    initial_skill_ids: set[str] | None = None,
    since_dt: datetime | None = None,
) -> list[dict]:
    events: list[dict] = []
    mem_items = memory_service.list_pending(profile)
    if initial_mem_ids is not None:
        new_mem = [item for item in mem_items if item["id"] not in initial_mem_ids]
    elif since_dt is not None:
        new_mem = [
            item
            for item in mem_items
            if item.get("created_at") is None or item["created_at"] >= since_dt
        ]
    else:
        new_mem = mem_items
    if new_mem:
        events.append(
            sse(
                "memory.pending",
                {
                    "items": [_serialize_pending_item(i) for i in new_mem],
                    "count": len(new_mem),
                },
            )
        )

    skill_items = skills_service.list_pending(profile)
    if initial_skill_ids is not None:
        new_skills = [item for item in skill_items if item["id"] not in initial_skill_ids]
    elif since_dt is not None:
        new_skills = [
            item
            for item in skill_items
            if item.get("created_at") is None or item["created_at"] >= since_dt
        ]
    else:
        new_skills = skill_items
    if new_skills:
        events.append(
            sse(
                "skills.pending",
                {
                    "items": [_serialize_pending_item(i) for i in new_skills],
                    "count": len(new_skills),
                },
            )
        )
    return events


async def _prepare_turn_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    conv_id: uuid.UUID,
    profile: str,
    file_ids: list[uuid.UUID] | None,
    skill_names: list[str] | None,
) -> tuple[dict | None, str | None]:
    user = await db.get(User, user_id)

    conv_files = list(
        (
            await db.execute(
                select(ConversationFile)
                .where(
                    ConversationFile.conversation_id == conv_id,
                    ConversationFile.user_id == user_id,
                    ConversationFile.status == "ready",
                )
                .order_by(ConversationFile.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    conv_file_ids = {f.id for f in conv_files}
    requested_ids = list(dict.fromkeys(file_ids or []))
    missing_requested = [fid for fid in requested_ids if fid not in conv_file_ids]

    global_attached: list[ConversationFile] = []
    if missing_requested:
        global_attached = list(
            (
                await db.execute(
                    select(ConversationFile)
                    .where(
                        ConversationFile.id.in_(missing_requested),
                        ConversationFile.user_id == user_id,
                        ConversationFile.status == "ready",
                        ConversationFile.is_global.is_(True),
                    )
                    .order_by(ConversationFile.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    all_context_files = [*conv_files, *global_attached]
    by_id = {f.id: f for f in all_context_files}
    attached_files = [by_id[fid] for fid in requested_ids if fid in by_id]

    cleaned_skills: list[str] = []
    if skill_names:
        disabled_set = set(provisioning.read_disabled_skills(profile))
        local_skills = {s["name"]: s for s in skills_service.list_skills(profile)}
        seen_skills: set[str] = set()
        for raw_name in skill_names:
            name = (raw_name or "").strip()
            if not name or name in seen_skills or name in disabled_set:
                continue
            seen_skills.add(name)
            cleaned_skills.append(name)
            if len(cleaned_skills) >= 10:
                break
    else:
        local_skills = {}

    payload: dict[str, Any] = {}
    if attached_files:
        payload["attachments"] = [
            {
                "id": str(f.id),
                "filename": f.filename,
                "ext": f.ext,
                "category": f.category,
                "size_bytes": f.size_bytes,
                "is_global": f.is_global,
            }
            for f in attached_files
        ]
    if cleaned_skills:
        payload["skills"] = cleaned_skills

    instruction_parts: list[str] = []
    profile_ctx = provisioning.build_profile_context(user)
    if profile_ctx:
        instruction_parts.append(profile_ctx)

    if cleaned_skills:
        skill_lines = ["本轮对话用户显式指定使用以下技能（请优先调用并遵循其工作流程）："]
        for sname in cleaned_skills:
            info = local_skills.get(sname)
            desc = (info.get("description") or "").strip() if info else ""
            skill_lines.append(f"- {sname}" + (f"：{desc}" if desc else ""))
        instruction_parts.append("\n".join(skill_lines))

    workspace_ctx = _build_workspace_instructions(conv_id, all_context_files, {f.id for f in attached_files})
    if workspace_ctx:
        instruction_parts.append(workspace_ctx)

    return (payload or None), ("\n\n".join(instruction_parts) if instruction_parts else None)


async def _run_pipeline_turn(
    db: AsyncSession,
    client: HermesClient,
    conv: Conversation,
    user_id: uuid.UUID,
    profile: str,
    assistant: Message,
    prompt_content: str,
    instructions: str | None,
    *,
    conversation_history: list[dict[str, str]] | None = None,
    max_seconds: int | None = None,
) -> AsyncIterator[dict]:
    initial_mem_ids = {item["id"] for item in memory_service.list_pending(profile)}
    initial_skill_ids = {item["id"] for item in skills_service.list_pending(profile)}

    run_started = time.time() - 2
    run = await client.create_run(
        prompt_content,
        conv.hermes_session_id,
        uuid.uuid4().hex,
        instructions=instructions,
        conversation_history=conversation_history,
    )
    run_id = str(run.get("run_id") or run.get("id"))
    conv.active_run_id = run_id
    conv.active_run_status = "running"
    assistant.hermes_run_id = run_id
    await db.commit()
    yield sse("run.started", {"run_id": run_id})

    pipeline = ChatPipeline(
        db,
        client,
        conv,
        assistant,
        run_id,
        started_at=run_started,
        max_seconds=max_seconds,
    )
    await pipeline.prepare()
    async for ev in pipeline.pump():
        yield ev
    if pipeline.terminal:
        await _settle_usage(db, user_id, assistant)
        for ev in _pending_events_since(profile, initial_mem_ids, initial_skill_ids):
            yield ev
        async for ev in _auto_title_events(db, conv, assistant, client):
            yield ev


async def stream_chat(
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    profile: str,
    api_key: str,
    content: str,
    file_ids: list[uuid.UUID] | None = None,
    skill_names: list[str] | None = None,
    max_seconds: int | None = None,
) -> AsyncIterator[dict]:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        now = datetime.now(timezone.utc)
        claimed = await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id, Conversation.active_run_id.is_(None))
            .values(active_run_id="pending", active_run_status="starting", last_message_at=now)
        )
        await db.commit()
        if not claimed.rowcount:
            yield sse("error", {"code": "run_in_progress", "detail": "当前会话有进行中的任务"})
            return
        await db.refresh(conv)
        client = HermesClient(profile, api_key)
        assistant = None
        try:
            if not conv.hermes_session_id:
                session = await client.create_session(conv.title)
                conv.hermes_session_id = str(session.get("id") or session.get("session_id") or "")
                await db.commit()

            user_payload, instructions = await _prepare_turn_context(
                db, user_id, conv.id, profile, file_ids, skill_names
            )

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=content,
                tool_payload=user_payload,
                status="completed",
                created_at=datetime.now(timezone.utc),
            )
            assistant = Message(
                conversation_id=conv.id,
                role="assistant",
                content="",
                status="streaming",
                created_at=user_msg.created_at + timedelta(milliseconds=1),
            )
            db.add_all([user_msg, assistant])
            conv.plan = None
            conv.last_message_at = datetime.now(timezone.utc)
            await db.commit()
            await usage.record_message(db, user_id)
            yield sse(
                "message.created",
                {"user_message_id": str(user_msg.id), "assistant_message_id": str(assistant.id)},
            )

            async for ev in _run_pipeline_turn(
                db,
                client,
                conv,
                user_id,
                profile,
                assistant,
                content,
                instructions,
                max_seconds=max_seconds,
            ):
                yield ev
        except HermesError as exc:
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "hermes_error", "status": exc.status_code, "detail": exc.detail})
        except Exception as exc:
            logger.exception("chat stream failed")
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "internal_error", "detail": str(exc)})
        finally:
            await client.aclose()


async def stream_regenerate(
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    profile: str,
    api_key: str,
    target_message_id: uuid.UUID,
    max_seconds: int | None = None,
) -> AsyncIterator[dict]:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        now = datetime.now(timezone.utc)
        claimed = await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id, Conversation.active_run_id.is_(None))
            .values(active_run_id="pending", active_run_status="starting", last_message_at=now)
        )
        await db.commit()
        if not claimed.rowcount:
            yield sse("error", {"code": "run_in_progress", "detail": "当前会话有进行中的任务"})
            return
        await db.refresh(conv)
        client = HermesClient(profile, api_key)
        assistant = None
        try:
            all_rows = list(
                (await db.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
            )
            ordered = sort_messages(all_rows)
            target_idx = next((idx for idx, m in enumerate(ordered) if m.id == target_message_id), None)
            if target_idx is None or ordered[target_idx].role != "assistant":
                conv.active_run_id = None
                conv.active_run_status = None
                await db.commit()
                yield sse("error", {"code": "invalid_target", "detail": "未找到可重新生成的助手消息"})
                return

            preceding_idx = next(
                (idx for idx in range(target_idx - 1, -1, -1) if ordered[idx].role == "user"),
                None,
            )
            if preceding_idx is None:
                conv.active_run_id = None
                conv.active_run_status = None
                await db.commit()
                yield sse("error", {"code": "invalid_target", "detail": "未找到对应的用户消息"})
                return

            target_msg = ordered[target_idx]
            user_msg = ordered[preceding_idx]
            history = _history_from_messages(ordered[:preceding_idx])

            delete_ids = {m.id for m in ordered[target_idx:]}
            if target_msg.hermes_run_id:
                for m in ordered:
                    if m.role == "tool" and m.hermes_run_id == target_msg.hermes_run_id:
                        delete_ids.add(m.id)
            if delete_ids:
                await db.execute(delete(Message).where(Message.id.in_(delete_ids)))

            prompt_payload = user_msg.tool_payload or {}
            file_ids: list[uuid.UUID] = []
            for att in prompt_payload.get("attachments") or []:
                if isinstance(att, dict) and att.get("id"):
                    try:
                        file_ids.append(uuid.UUID(str(att["id"])))
                    except ValueError:
                        pass
            skill_names = [str(s) for s in (prompt_payload.get("skills") or []) if str(s).strip()]

            _, instructions = await _prepare_turn_context(
                db, user_id, conv.id, profile, file_ids, skill_names
            )

            # Create a fresh Hermes session so discarded turns never pollute agent history.
            session = await client.create_session(conv.title)
            conv.hermes_session_id = str(session.get("id") or session.get("session_id") or "")

            assistant_ts = max(datetime.now(timezone.utc), user_msg.created_at + timedelta(milliseconds=1))
            assistant = Message(
                conversation_id=conv.id,
                role="assistant",
                content="",
                status="streaming",
                created_at=assistant_ts,
            )
            db.add(assistant)
            conv.plan = None
            conv.last_message_at = datetime.now(timezone.utc)
            await db.commit()
            await usage.record_message(db, user_id)
            yield sse(
                "message.created",
                {
                    "user_message_id": str(user_msg.id),
                    "assistant_message_id": str(assistant.id),
                    "replaced_message_id": str(target_message_id),
                },
            )

            async for ev in _run_pipeline_turn(
                db,
                client,
                conv,
                user_id,
                profile,
                assistant,
                user_msg.content,
                instructions,
                conversation_history=history or None,
                max_seconds=max_seconds,
            ):
                yield ev
        except HermesError as exc:
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "hermes_error", "status": exc.status_code, "detail": exc.detail})
        except Exception as exc:
            logger.exception("chat regenerate failed")
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "internal_error", "detail": str(exc)})
        finally:
            await client.aclose()


async def stream_edit(
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    profile: str,
    api_key: str,
    target_message_id: uuid.UUID,
    content: str,
    file_ids: list[uuid.UUID] | None = None,
    skill_names: list[str] | None = None,
    max_seconds: int | None = None,
) -> AsyncIterator[dict]:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        now = datetime.now(timezone.utc)
        claimed = await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id, Conversation.active_run_id.is_(None))
            .values(active_run_id="pending", active_run_status="starting", last_message_at=now)
        )
        await db.commit()
        if not claimed.rowcount:
            yield sse("error", {"code": "run_in_progress", "detail": "当前会话有进行中的任务"})
            return
        await db.refresh(conv)
        client = HermesClient(profile, api_key)
        assistant = None
        try:
            all_rows = list(
                (await db.execute(select(Message).where(Message.conversation_id == conv.id))).scalars().all()
            )
            ordered = sort_messages(all_rows)
            target_idx = next((idx for idx, m in enumerate(ordered) if m.id == target_message_id), None)
            if target_idx is None or ordered[target_idx].role != "user":
                conv.active_run_id = None
                conv.active_run_status = None
                await db.commit()
                yield sse("error", {"code": "invalid_target", "detail": "未找到可编辑的用户消息"})
                return

            history = _history_from_messages(ordered[:target_idx])
            delete_ids = {m.id for m in ordered[target_idx:]}
            if delete_ids:
                await db.execute(delete(Message).where(Message.id.in_(delete_ids)))

            user_payload, instructions = await _prepare_turn_context(
                db, user_id, conv.id, profile, file_ids, skill_names
            )

            # Create a fresh Hermes session so discarded turns never pollute agent history.
            session = await client.create_session(conv.title)
            conv.hermes_session_id = str(session.get("id") or session.get("session_id") or "")

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=content,
                tool_payload=user_payload,
                status="completed",
                created_at=datetime.now(timezone.utc),
            )
            assistant = Message(
                conversation_id=conv.id,
                role="assistant",
                content="",
                status="streaming",
                created_at=user_msg.created_at + timedelta(milliseconds=1),
            )
            db.add_all([user_msg, assistant])
            conv.plan = None
            conv.last_message_at = datetime.now(timezone.utc)
            await db.commit()
            await usage.record_message(db, user_id)
            yield sse(
                "message.created",
                {
                    "user_message_id": str(user_msg.id),
                    "assistant_message_id": str(assistant.id),
                    "replaced_message_id": str(target_message_id),
                },
            )

            async for ev in _run_pipeline_turn(
                db,
                client,
                conv,
                user_id,
                profile,
                assistant,
                content,
                instructions,
                conversation_history=history or None,
                max_seconds=max_seconds,
            ):
                yield ev
        except HermesError as exc:
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "hermes_error", "status": exc.status_code, "detail": exc.detail})
        except Exception as exc:
            logger.exception("chat edit failed")
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "internal_error", "detail": str(exc)})
        finally:
            await client.aclose()


async def stream_reconnect(
    conv_id: uuid.UUID,
    profile: str,
    api_key: str,
    run_id: str,
    max_seconds: int | None = None,
) -> AsyncIterator[dict]:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        result = await db.execute(
            select(Message).where(Message.conversation_id == conv.id, Message.hermes_run_id == run_id, Message.role == "assistant")
        )
        assistant = result.scalars().first()
        if assistant is None:
            yield sse("error", {"code": "run_not_found", "detail": "未找到对应的运行记录"})
            return
        client = HermesClient(profile, api_key)
        try:
            yield sse("run.reconnected", {"run_id": run_id, "assistant_message_id": str(assistant.id)})
            pipeline = ChatPipeline(db, client, conv, assistant, run_id, max_seconds=max_seconds)
            pipeline.buffer = [assistant.content or ""]
            await pipeline.prepare()
            async for ev in pipeline.pump():
                yield ev
            if pipeline.terminal:
                await _settle_usage(db, conv.user_id, assistant)
                since_dt = assistant.created_at - timedelta(seconds=2) if assistant.created_at else None
                for ev in _pending_events_since(profile, since_dt=since_dt):
                    yield ev
                async for ev in _auto_title_events(db, conv, assistant, client):
                    yield ev
        except HermesError as exc:
            assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "hermes_error", "status": exc.status_code, "detail": exc.detail})
        finally:
            await client.aclose()
