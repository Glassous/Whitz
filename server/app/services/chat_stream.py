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
from app.services import (
    cos,
    cross_chat_memory,
    file_provenance,
    limits,
    membership,
    memory_service,
    profile_context,
    run_supervisor,
    scheduler_service,
    skills_service,
    telemetry,
    titles,
    usage,
)
from app.services.agent_client import AgentClient, AgentError

logger = logging.getLogger("whitz.chat")

TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}
TERMINAL_STATUSES = {
    "completed": "run.completed",
    "failed": "run.failed",
    "cancelled": "run.cancelled",
    "interrupted": "run.interrupted",
}
ROLE_ORDER = {"user": 0, "assistant": 1, "tool": 2}


def sse(name: str, payload: dict, *, event_id: str | None = None) -> dict:
    frame: dict[str, Any] = {"event": name, "data": json.dumps(payload, ensure_ascii=False)}
    if event_id:
        frame["id"] = str(event_id)
    return frame


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


async def _recent_conversation_history(
    db: AsyncSession,
    conv_id: uuid.UUID,
    *,
    limit: int = 24,
) -> list[dict[str, str]]:
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv_id,
                    Message.role.in_(("user", "assistant")),
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    rows.reverse()
    return _history_from_messages(sort_messages(rows))


async def _settle_usage(db: AsyncSession, user_id: uuid.UUID, assistant: Message) -> None:
    """Record dashboard usage and deduct credits strictly once per assistant message."""
    await run_supervisor.settle_usage_once(db, user_id, assistant)


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
    return (
        cleaned == "write_workspace_file"
        or cleaned.endswith("write_workspace_file")
        or cleaned == "edit_workspace_file"
        or cleaned.endswith("edit_workspace_file")
    )


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
        client: AgentClient,
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
        self.pending_tools_by_call: dict[str, Message] = {}
        self.pending_tools: dict[str, list[Message]] = {}
        self.existing_tools_by_call: dict[str, Message] = {}
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
        self.first_token_at: float | None = None
        if started_at is not None:
            self.started_at = started_at
        elif assistant.created_at is not None:
            self.started_at = assistant.created_at.timestamp()
        else:
            self.started_at = time.time()
        self.run_started_dt = datetime.fromtimestamp(max(0.0, self.started_at - 2.0), tz=timezone.utc)

    @staticmethod
    def _tool_key(tool: str, args) -> str:
        return f"{tool}\x00{json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)}"

    async def prepare(self) -> None:
        if not self.assistant.run_id:
            return
        result = await self.db.execute(
            select(Message)
            .where(
                Message.conversation_id == self.conv.id,
                Message.run_id == self.run_id,
                Message.role == "tool",
            )
            .order_by(Message.created_at)
        )
        for row in result.scalars():
            payload = row.tool_payload or {}
            call_id = payload.get("call_id")
            if isinstance(call_id, str) and call_id:
                self.existing_tools_by_call[call_id] = row
            args = payload.get("args")
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

    @staticmethod
    def _unwrap_tool_result(text: str) -> str:
        text = text.strip()
        if text.startswith("<untrusted_tool_result"):
            end_tag = text.find(">")
            if end_tag >= 0:
                text = text[end_tag + 1 :]
        suffix = "</untrusted_tool_result>"
        if text.rstrip().endswith(suffix):
            text = text.rstrip()[: -len(suffix)]
        return text.strip()

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
        self.conv.pending_control = None
        self.conv.last_message_at = datetime.now(timezone.utc)

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
            except AgentError:
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
                if self.first_token_at is None:
                    self.first_token_at = time.time()
                self.buffer.append(text)
                yield sse("message.delta", {"text": text})
                await self._flush()

        elif name in ("message.interim", "commentary"):
            text = payload.get("text") or payload.get("delta") or ""
            text = text.strip() if isinstance(text, str) else ""
            if not text:
                yield sse(name, payload)
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

        elif name == "graph.node":
            extra = dict(self.assistant.tool_payload or {})
            runtime = dict(extra.get("runtime") or {})
            if payload.get("route"):
                runtime["route"] = payload["route"]
            if payload.get("model"):
                runtime["model"] = payload["model"]
            if runtime:
                extra["runtime"] = runtime
                self.assistant.tool_payload = extra
            yield sse("graph.node", payload)

        elif name == "plan.updated":
            items = parse_todos(payload.get("items") if "items" in payload else payload)
            if items is not None:
                self.plan = {"items": items}
                self.conv.plan = self.plan
                await self._persist_reasoning()
                yield sse("plan.updated", self.plan)

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
            args = payload.get("args") if "args" in payload else payload.get("preview")
            preview = payload.get("preview") if "preview" in payload else args
            call_id = payload.get("call_id")
            key = self._tool_key(tool, args)

            row = None
            if isinstance(call_id, str) and call_id and call_id in self.existing_tools_by_call:
                row = self.existing_tools_by_call.pop(call_id)
            else:
                reused = self.existing_tools.get(key)
                if reused:
                    row = reused.pop(0)

            if row is not None:
                row.status = "running"
                row.tool_payload = {
                    **(row.tool_payload or {}),
                    "args": args,
                    "call_id": call_id,
                    "status": "running",
                }
            else:
                row = Message(
                    conversation_id=self.conv.id,
                    role="tool",
                    tool_name=tool,
                    tool_payload={"args": args, "call_id": call_id, "status": "running"},
                    status="running",
                    run_id=self.run_id,
                )
                self.db.add(row)
            await self.db.commit()
            if isinstance(call_id, str) and call_id:
                self.pending_tools_by_call[call_id] = row
            self.pending_tools.setdefault(tool, []).append(row)

            block = self._reasoning_block()
            tools_list = block.setdefault("tools", [])
            if not (call_id and any(t.get("call_id") == call_id for t in tools_list)):
                tools_list.append(
                    {
                        "name": tool,
                        "call_id": call_id,
                        "args": self._clip(args),
                        "status": "running",
                    }
                )

            out_ev: dict[str, Any] = {
                "tool": tool,
                "preview": preview,
                "args": args,
                "message_id": str(row.id),
            }
            if call_id is not None:
                out_ev["call_id"] = call_id
            yield sse("tool.started", out_ev)

            if tool == "todo_list":
                items = parse_todos(args if args is not None else preview)
                if items is not None:
                    self.plan = {"items": items}
                    self.conv.plan = self.plan
                    await self.db.commit()
                    yield sse("plan.updated", self.plan)

        elif name == "tool.completed":
            tool = payload.get("tool") or "tool"
            preview = payload.get("preview")
            result_val = payload.get("result") if "result" in payload else preview
            error = payload.get("error")
            duration = payload.get("duration")
            duration_ms = payload.get("duration_ms") if payload.get("duration_ms") is not None else duration
            call_id = payload.get("call_id")

            row = None
            if isinstance(call_id, str) and call_id and call_id in self.pending_tools_by_call:
                row = self.pending_tools_by_call.pop(call_id)
                q = self.pending_tools.get(tool) or []
                if row in q:
                    q.remove(row)
            else:
                rows = self.pending_tools.get(tool) or []
                row = rows.pop(0) if rows else None

            args_val = payload.get("args")
            if row is not None:
                if args_val is None:
                    args_val = (row.tool_payload or {}).get("args")
                row.tool_payload = {
                    "args": args_val,
                    "result": result_val,
                    "duration": duration,
                    "duration_ms": duration_ms,
                    "error": error,
                    "call_id": call_id or (row.tool_payload or {}).get("call_id"),
                    "status": "failed" if error else "completed",
                }
                row.status = "failed" if error else "completed"
                await self.db.commit()

            # Update reasoning block tool record
            for blk in reversed(self.reasoning):
                matched_tool = None
                for t_rec in reversed(blk.get("tools") or []):
                    if call_id and t_rec.get("call_id") == call_id:
                        matched_tool = t_rec
                        break
                    if not call_id and t_rec.get("name") == tool and t_rec.get("status") == "running":
                        matched_tool = t_rec
                        break
                if matched_tool is not None:
                    matched_tool["status"] = "failed" if error else "completed"
                    matched_tool["result"] = self._clip(result_val, 1200)
                    if duration_ms is not None:
                        matched_tool["duration_ms"] = duration_ms
                    if error:
                        matched_tool["error"] = error
                    await self._persist_reasoning()
                    break

            out_ev: dict[str, Any] = {
                "tool": tool,
                "preview": preview,
                "result": result_val,
                "args": args_val,
                "error": error,
                "duration": duration,
                "duration_ms": duration_ms,
                "message_id": str(row.id) if row else None,
            }
            if call_id is not None:
                out_ev["call_id"] = call_id
            yield sse("tool.completed", out_ev)

            if tool == "todo_list":
                items = parse_todos(result_val if result_val is not None else preview)
                if items is not None:
                    self.plan = {"items": items}
                    self.conv.plan = self.plan
                    await self.db.commit()
                    yield sse("plan.updated", self.plan)
            if not error and _is_write_workspace_tool(tool):
                parsed_fid = _extract_artifact_file_id(result_val if result_val is not None else preview)
                for art in await self._collect_new_artifacts(parsed_fid):
                    yield sse("workspace.file_created", art)

        elif name in ("approval.request", "clarify.request"):
            request_id, generation = await self._control_ids(payload)
            detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
            out_payload: dict[str, Any] = {
                "kind": "approval" if name == "approval.request" else "clarify",
                "request_id": request_id,
                "execution_generation": generation,
                "tool": payload.get("tool"),
                "preview": payload.get("preview"),
                "detail": detail,
            }
            if isinstance(detail, dict):
                if detail.get("code") is not None:
                    out_payload["code"] = detail.get("code")
                if detail.get("language") is not None:
                    out_payload["language"] = detail.get("language")
                desc = detail.get("reason") or detail.get("description")
                if desc is not None:
                    out_payload["description"] = desc
            self.assistant.status = "waiting"
            self.conv.active_run_status = (
                "waiting_for_approval" if name == "approval.request" else "waiting_for_clarify"
            )
            self.conv.pending_control = out_payload
            await self.db.commit()
            yield sse(name, out_payload)

        elif name in ("control.resolved", "run.resumed"):
            self.conv.pending_control = None
            if self.conv.active_run_id == self.run_id:
                self.conv.active_run_status = "running"
            if self.assistant.status == "waiting":
                self.assistant.status = "streaming"
            await self.db.commit()
            yield sse(name, payload)

        elif name == "message.reaction":
            yield sse("message.reaction", payload)

        elif name == "run.completed":
            self.terminal = True
            for art in await self._collect_new_artifacts():
                yield sse("workspace.file_created", art)
            output = payload.get("output")
            self.assistant.content = output if output else "".join(self.buffer)
            self.assistant.status = "completed"
            if isinstance(payload.get("plan"), dict):
                self.plan = payload["plan"]
            extra = dict(self.assistant.tool_payload or {})
            runtime = dict(extra.get("runtime") or {})
            if isinstance(payload.get("runtime"), dict):
                runtime.update(payload["runtime"])
            for k in ("route", "model"):
                if payload.get(k):
                    runtime[k] = payload[k]
            if self.started_at:
                now_ts = time.time()
                runtime.setdefault("duration_ms", max(0, int((now_ts - self.started_at) * 1000)))
                if self.first_token_at is not None:
                    runtime.setdefault("ttft_ms", max(0, int((self.first_token_at - self.started_at) * 1000)))
            extra["usage"] = payload.get("usage")
            extra["runtime"] = runtime or payload.get("runtime")
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
            if isinstance(payload.get("plan"), dict):
                self.plan = payload["plan"]
            extra = dict(self.assistant.tool_payload or {})
            for key in ("usage", "runtime"):
                if payload.get(key) is not None:
                    extra[key] = payload.get(key)
            runtime = dict(extra.get("runtime") or {})
            if self.started_at:
                runtime.setdefault("duration_ms", max(0, int((time.time() - self.started_at) * 1000)))
            if runtime:
                extra["runtime"] = runtime
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
                {
                    "error": error,
                    "output": self.assistant.content,
                    "plan": self.plan,
                    "reasoning": self.reasoning or None,
                },
            )

        else:
            yield sse(name, payload)

    async def _run_state(self) -> tuple[str, dict] | None:
        try:
            run = await self.client.get_run(self.run_id)
        except AgentError:
            return None
        return str(run.get("status") or ""), run

    async def _abort_timeout(self) -> None:
        self.terminal = True
        self.assistant.content = "".join(self.buffer)
        self.assistant.status = "failed"
        try:
            await asyncio.wait_for(self.client.cancel_run(self.run_id), timeout=10)
        except (AgentError, asyncio.TimeoutError):
            pass
        await self._clear_active()
        await self.db.commit()

    async def _iter_agent_events(
        self,
        *,
        last_event_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict, str | None]]:
        if hasattr(self.client, "stream_events_with_id"):
            async for ev_name, payload, ev_id in self.client.stream_events_with_id(
                self.run_id, last_event_id=last_event_id
            ):
                yield ev_name, payload, ev_id
        else:
            async for ev_name, payload in self.client.stream_events(self.run_id, last_event_id=last_event_id):
                yield ev_name, payload, None

    async def pump(self, *, last_event_id: str | None = None) -> AsyncIterator[dict]:
        settings = get_settings()
        max_seconds = self.max_seconds or settings.run_max_seconds
        deadline = time.monotonic() + max_seconds
        timed_out = False
        cursor = last_event_id

        # Retry transient SSE drops with Last-Event-ID up to 3 times before falling back to polling
        for attempt in range(3):
            if self.terminal or time.monotonic() >= deadline:
                break
            try:
                async with asyncio.timeout(max(1.0, deadline - time.monotonic())):
                    async for name, payload, ev_id in self._iter_agent_events(last_event_id=cursor):
                        if ev_id:
                            cursor = ev_id
                        async for ev in self.handle(name, payload):
                            if ev_id and "id" not in ev:
                                ev["id"] = ev_id
                            yield ev
                        if self.terminal:
                            break
                break
            except TimeoutError:
                timed_out = True
                break
            except AgentError as exc:
                if exc.status_code == 404:
                    break
                probe = await self._run_state()
                if probe is None:
                    if attempt < 2 and time.monotonic() < deadline:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    raise
                run_status, _ = probe
                if run_status in TERMINAL_STATUSES:
                    break
                if attempt < 2 and time.monotonic() < deadline:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                break

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
                    for key in ("output", "usage", "runtime", "error", "plan", "reasoning", "completed", "partial", "interrupted")
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
) -> AsyncIterator[dict]:
    if conv.kind == "main" or conv.title not in ("新对话", "新旁聊") or assistant is None or assistant.status != "completed":
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
        if conv.kind == "main" or conv.title not in ("新对话", "新旁聊"):
            return
        conv.title = title
        await db.commit()
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
    total_library_count: int = 0,
    provenance_map: dict[uuid.UUID, dict[str, Any]] | None = None,
) -> str | None:
    if not workspace_files:
        return None
    header = f"当前可用的资料库与工作区文件（conversation_id: {conv_id}，当前列出 {len(workspace_files)} 个"
    if total_library_count > len(workspace_files):
        header += f"，用户资料库共 {total_library_count} 个已就绪文件"
    header += "）："
    lines = [header]
    prov = provenance_map or {}
    for f in workspace_files:
        tags: list[str] = []
        if f.id in attached_ids:
            tags.append("本轮新附带")
        if f.conversation_id != conv_id:
            tags.append("资料库共享")
        p = prov.get(f.id) or {}
        conv_title = p.get("conversation_title")
        qa_snippet = p.get("qa_snippet")
        if conv_title and f.conversation_id != conv_id:
            tags.append(f"来自会话《{conv_title}》")
        if qa_snippet:
            tags.append(f"问答：「{qa_snippet}」")
        tag_str = f" [{' · '.join(tags)}]" if tags else ""
        lines.append(
            f"- {f.filename}{tag_str} (file_id={f.id}, category={f.category}, mime={f.mime_type}, size={f.size_bytes} bytes)"
        )
    lines.append(
        "若用户询问或需要处理以上任意文件或资料库中其他历史文件，请优先使用 rag_search_workspace 或 list_workspace_files / read_workspace_file 按需读取真实内容；"
        "若需要向用户交付报告、网页、表格、代码或文档等纯文本产物，可调用 write_workspace_file 创建或 edit_workspace_file 局部修改工作区文件，并在正文中以 ```deliverable 卡片指定出来。"
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


async def _pending_events_since(
    db: AsyncSession,
    user_id: uuid.UUID,
    initial_mem_ids: set[str] | None = None,
    initial_skill_ids: set[str] | None = None,
    initial_schedule_ids: set[str] | None = None,
    since_dt: datetime | None = None,
) -> list[dict]:
    events: list[dict] = []
    mem_items = await memory_service.list_pending(db, user_id)
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

    skill_items = await skills_service.list_pending(db, user_id)
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

    schedule_items = await scheduler_service.list_pending(db, user_id)
    if initial_schedule_ids is not None:
        new_schedules = [item for item in schedule_items if item["id"] not in initial_schedule_ids]
    elif since_dt is not None:
        new_schedules = [
            item
            for item in schedule_items
            if item.get("created_at") is None or item["created_at"] >= since_dt
        ]
    else:
        new_schedules = schedule_items
    if new_schedules:
        events.append(
            sse(
                "schedules.pending",
                {
                    "items": [_serialize_pending_item(i) for i in new_schedules],
                    "count": len(new_schedules),
                },
            )
        )
    return events


async def _prepare_turn_context(
    db: AsyncSession,
    user: User,
    conv: Conversation,
    file_ids: list[uuid.UUID] | None,
    skill_names: list[str] | None,
    query_text: str = "",
) -> dict[str, Any]:
    conv_id = conv.id
    conv_files = list(
        (
            await db.execute(
                select(ConversationFile)
                .where(
                    ConversationFile.conversation_id == conv_id,
                    ConversationFile.user_id == user.id,
                    ConversationFile.status == "ready",
                )
                .order_by(ConversationFile.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    conv_file_ids = {f.id for f in conv_files}
    inline_ids = file_provenance.extract_inline_file_ids(query_text)
    requested_ids = list(dict.fromkeys([*(file_ids or []), *inline_ids]))
    missing_requested = [fid for fid in requested_ids if fid not in conv_file_ids]

    global_attached: list[ConversationFile] = []
    if missing_requested:
        global_attached = list(
            (
                await db.execute(
                    select(ConversationFile)
                    .where(
                        ConversationFile.id.in_(missing_requested),
                        ConversationFile.user_id == user.id,
                        ConversationFile.status == "ready",
                    )
                    .order_by(ConversationFile.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    # Include recent library files from across all chats (capped to avoid prompt bloat)
    seen_file_ids = {f.id for f in [*conv_files, *global_attached]}
    recent_library_files = list(
        (
            await db.execute(
                select(ConversationFile)
                .where(
                    ConversationFile.user_id == user.id,
                    ConversationFile.status == "ready",
                )
                .order_by(ConversationFile.created_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    extra_library = [f for f in recent_library_files if f.id not in seen_file_ids]
    all_context_files = [*conv_files, *global_attached, *extra_library[: max(0, 30 - len(seen_file_ids))]]
    total_library_count = len(recent_library_files)
    by_id = {f.id: f for f in all_context_files}
    attached_files = [by_id[fid] for fid in requested_ids if fid in by_id]

    all_user_skills = await skills_service.list_skills(db, user)
    enabled_skills = [s for s in all_user_skills if s.get("enabled")]
    by_skill_name = {s["name"]: s for s in enabled_skills}
    hidden_builtins = skills_service.hidden_builtin_names()

    cleaned_skills: list[str] = []
    if skill_names:
        seen_skills: set[str] = set()
        for raw_name in skill_names:
            name = (raw_name or "").strip()
            if not name or name in seen_skills or name.lower() in hidden_builtins:
                continue
            # Preserve explicit skill if enabled or not in disabled list
            all_map = {s["name"]: s for s in all_user_skills}
            if name in all_map and not all_map[name].get("enabled"):
                continue
            seen_skills.add(name)
            cleaned_skills.append(name)
            if len(cleaned_skills) >= 10:
                break

    user_payload: dict[str, Any] = {}
    if attached_files:
        user_payload["attachments"] = [
            {
                "id": str(f.id),
                "filename": f.filename,
                "ext": f.ext,
                "category": f.category,
                "size_bytes": f.size_bytes,
                "is_global": True,
            }
            for f in attached_files
        ]
    if cleaned_skills:
        user_payload["skills"] = cleaned_skills

    provenance_map = await file_provenance.resolve_files_provenance(db, user, all_context_files)

    attachments_meta = [
        {
            "id": str(f.id),
            "file_id": str(f.id),
            "filename": f.filename,
            "ext": f.ext,
            "category": f.category,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "is_global": True,
            "scope": "conversation" if f.conversation_id == conv_id else "library",
            "attached": f.id in {af.id for af in attached_files},
            "conversation_id": str(f.conversation_id) if f.conversation_id else None,
            "conversation_title": (provenance_map.get(f.id) or {}).get("conversation_title"),
            "message_id": str(f.message_id) if f.message_id else None,
            "turn_role": (provenance_map.get(f.id) or {}).get("turn_role"),
            "qa_snippet": (provenance_map.get(f.id) or {}).get("qa_snippet"),
        }
        for f in all_context_files
    ]
    active_skills_meta = [
        {
            "name": s["name"],
            "description": s.get("description") or "",
            "category": s.get("category"),
            "content": s.get("content") or "",
        }
        for s in enabled_skills
    ]

    instruction_parts: list[str] = []
    prof_ctx = profile_context.build_profile_context(user)
    if prof_ctx:
        instruction_parts.append(prof_ctx)

    if cleaned_skills:
        skill_lines = ["本轮对话用户显式指定使用以下技能（请优先调用并遵循其工作流程）："]
        for sname in cleaned_skills:
            info = by_skill_name.get(sname)
            desc = (info.get("description") or "").strip() if info else ""
            skill_lines.append(f"- {sname}" + (f"：{desc}" if desc else ""))
        instruction_parts.append("\n".join(skill_lines))

    workspace_ctx = _build_workspace_instructions(
        conv_id,
        all_context_files,
        {f.id for f in attached_files},
        total_library_count=total_library_count,
        provenance_map=provenance_map,
    )
    if workspace_ctx:
        instruction_parts.append(workspace_ctx)

    rolling_summary = ""
    cross_chat_context = ""
    if conv.kind == "main":
        try:
            mem_ctx = await cross_chat_memory.build_main_chat_memory_context(
                db, user, conv, query_text=query_text
            )
            rolling_summary = mem_ctx.get("rolling_summary") or ""
            cross_chat_context = mem_ctx.get("cross_chat_context") or ""
        except Exception as exc:
            logger.warning("Main chat cross-session memory lookup failed: %s", exc)
            rolling_summary = (conv.rolling_summary or "").strip()

    return {
        "user_payload": user_payload or None,
        "instructions": "\n\n".join(instruction_parts) if instruction_parts else None,
        "profile_context": prof_ctx,
        "persona": user.persona or "",
        "assistant_name": (getattr(user, "assistant_name", None) or "").strip() or "Whitz",
        "conversation_kind": conv.kind or "side",
        "rolling_summary": rolling_summary,
        "cross_chat_context": cross_chat_context,
        "timezone": (getattr(user, "timezone", None) or "").strip() or "Asia/Shanghai",
        "memory_enabled": bool(user.memory_enabled and user.memory_consented_at),
        "memory_require_confirm": bool(user.memory_require_confirm),
        "ai_reactions_enabled": bool(getattr(user, "ai_reactions_enabled", True)),
        "attachments": attachments_meta,
        "attached_file_ids": [f.id for f in attached_files],
        "skills": active_skills_meta,
        "requested_skills": cleaned_skills,
    }


async def _launch_supervised_turn(
    db: AsyncSession,
    client: AgentClient,
    conv: Conversation,
    user: User,
    assistant: Message,
    user_msg_id: uuid.UUID | None,
    prompt_content: str,
    turn_ctx: dict[str, Any],
    *,
    conversation_history: list[dict[str, str]] | None = None,
    model_route: str = "auto",
    max_seconds: int | None = None,
    run_slot: str | None = None,
    idempotency_key: str | None = None,
    allow_hitl: bool = True,
    scheduled_run_id: uuid.UUID | None = None,
) -> tuple[run_supervisor.SupervisedRun, asyncio.Queue[dict[str, Any] | None], str]:
    initial_mem_ids = {item["id"] for item in await memory_service.list_pending(db, user.id)}
    initial_skill_ids = {item["id"] for item in await skills_service.list_pending(db, user.id)}
    initial_schedule_ids = {item["id"] for item in await scheduler_service.list_pending(db, user.id)}

    run_started = time.time()
    run = await client.create_run(
        thread_id=conv.thread_id,
        user_id=str(user.id),
        agent_namespace=user.agent_namespace,
        agent_api_key=user.agent_api_key,
        conversation_id=str(conv.id),
        conversation_kind=str(turn_ctx.get("conversation_kind") or conv.kind or "side"),
        assistant_name=str(turn_ctx.get("assistant_name") or getattr(user, "assistant_name", None) or "Whitz"),
        rolling_summary=turn_ctx.get("rolling_summary") or None,
        cross_chat_context=turn_ctx.get("cross_chat_context") or None,
        input_text=prompt_content,
        instructions=turn_ctx.get("instructions"),
        conversation_history=conversation_history,
        model_route=model_route or "auto",
        attachments=turn_ctx.get("attachments"),
        skills=turn_ctx.get("skills"),
        requested_skills=turn_ctx.get("requested_skills"),
        persona=turn_ctx.get("persona") or "",
        profile_context=turn_ctx.get("profile_context"),
        timezone=turn_ctx.get("timezone") or getattr(user, "timezone", None) or "Asia/Shanghai",
        memory_enabled=bool(turn_ctx.get("memory_enabled")),
        memory_require_confirm=bool(turn_ctx.get("memory_require_confirm", True)),
        ai_reactions_enabled=bool(turn_ctx.get("ai_reactions_enabled", True)),
        allow_hitl=allow_hitl,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
    )
    run_id = str(run.get("run_id") or run.get("id"))
    conv.active_run_id = run_id
    conv.active_run_status = "running"
    conv.pending_control = None
    assistant.run_id = run_id
    await db.commit()

    # Launch detached Single-Writer RunSupervisor (survives HTTP SSE disconnects completely!)
    sup, q = run_supervisor.start_supervised_run(
        run_id=run_id,
        conv_id=conv.id,
        user_id=user.id,
        assistant_id=assistant.id,
        user_msg_id=user_msg_id,
        user_content=prompt_content,
        client=client,
        session_factory=SessionLocal,
        started_at=run_started,
        max_seconds=max_seconds,
        run_slot=run_slot,
        initial_mem_ids=initial_mem_ids,
        initial_skill_ids=initial_skill_ids,
        initial_schedule_ids=initial_schedule_ids,
        scheduled_run_id=scheduled_run_id,
    )
    return sup, q, run_id


async def stream_chat(
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    namespace: str,
    api_key: str,
    content: str,
    file_ids: list[uuid.UUID] | None = None,
    skill_names: list[str] | None = None,
    model_route: str = "auto",
    max_seconds: int | None = None,
    run_slot: str | None = None,
    idempotency_key: str | None = None,
) -> AsyncIterator[dict]:
    sup: run_supervisor.SupervisedRun | None = None
    q: asyncio.Queue[dict[str, Any] | None] | None = None
    run_slot_handed_off = False

    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        user = await db.get(User, user_id)
        if conv is None or user is None:
            if run_slot:
                await limits.release_run(user_id, run_slot)
            yield sse("error", {"code": "not_found"})
            return
        now = datetime.now(timezone.utc)
        claimed = await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id, Conversation.active_run_id.is_(None))
            .values(active_run_id="pending", active_run_status="starting", pending_control=None, last_message_at=now)
        )
        await db.commit()
        if not claimed.rowcount:
            if run_slot:
                await limits.release_run(user_id, run_slot)
            yield sse("error", {"code": "run_in_progress", "detail": "当前会话有进行中的任务"})
            return
        await db.refresh(conv)
        client = AgentClient(namespace, api_key)
        assistant = None
        try:
            if not conv.thread_id:
                conv.thread_id = str(uuid.uuid4())
                await db.commit()

            # Load recent verbatim history from PG before inserting this turn (clean per-run agent checkpoints)
            history = await _recent_conversation_history(db, conv.id, limit=24)
            turn_ctx = await _prepare_turn_context(db, user, conv, file_ids, skill_names, query_text=content)

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=content,
                tool_payload=turn_ctx["user_payload"],
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
            await db.flush()
            attached_fids = turn_ctx.get("attached_file_ids") or []
            if attached_fids:
                await db.execute(
                    update(ConversationFile)
                    .where(
                        ConversationFile.id.in_(attached_fids),
                        ConversationFile.conversation_id == conv.id,
                        ConversationFile.user_id == user.id,
                        ConversationFile.message_id.is_(None),
                    )
                    .values(message_id=user_msg.id)
                )
            conv.plan = None
            conv.last_message_at = datetime.now(timezone.utc)
            await db.commit()
            await usage.record_message(db, user_id)
            yield sse(
                "message.created",
                {"user_message_id": str(user_msg.id), "assistant_message_id": str(assistant.id)},
            )

            sup, q, run_id = await _launch_supervised_turn(
                db,
                client,
                conv,
                user,
                assistant,
                user_msg.id,
                content,
                turn_ctx,
                conversation_history=history or None,
                model_route=model_route,
                max_seconds=max_seconds,
                run_slot=run_slot,
                idempotency_key=idempotency_key,
            )
            run_slot_handed_off = True
            yield sse("run.started", {"run_id": run_id})
        except AgentError as exc:
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            conv.pending_control = None
            await db.commit()
            if run_slot and not run_slot_handed_off:
                await limits.release_run(user_id, run_slot)
            await client.aclose()
            yield sse("error", {"code": "agent_error", "status": exc.status_code, "detail": exc.detail})
            return
        except Exception as exc:
            logger.exception("chat stream failed")
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            conv.pending_control = None
            await db.commit()
            if run_slot and not run_slot_handed_off:
                await limits.release_run(user_id, run_slot)
            await client.aclose()
            yield sse("error", {"code": "internal_error", "detail": str(exc)})
            return

    # DB session is now CLOSED; stream strictly as a read-only subscriber so client disconnect
    # never holds a DB connection or interrupts RunSupervisor!
    if sup is not None and q is not None:
        async for ev in run_supervisor.iter_subscriber_queue(sup, q):
            yield ev


async def stream_regenerate(
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    namespace: str,
    api_key: str,
    target_message_id: uuid.UUID,
    model_route: str = "auto",
    max_seconds: int | None = None,
    run_slot: str | None = None,
    idempotency_key: str | None = None,
) -> AsyncIterator[dict]:
    sup: run_supervisor.SupervisedRun | None = None
    q: asyncio.Queue[dict[str, Any] | None] | None = None
    run_slot_handed_off = False
    old_thread_id: str | None = None

    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        user = await db.get(User, user_id)
        if conv is None or user is None:
            if run_slot:
                await limits.release_run(user_id, run_slot)
            yield sse("error", {"code": "not_found"})
            return
        now = datetime.now(timezone.utc)
        claimed = await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id, Conversation.active_run_id.is_(None))
            .values(active_run_id="pending", active_run_status="starting", pending_control=None, last_message_at=now)
        )
        await db.commit()
        if not claimed.rowcount:
            if run_slot:
                await limits.release_run(user_id, run_slot)
            yield sse("error", {"code": "run_in_progress", "detail": "当前会话有进行中的任务"})
            return
        await db.refresh(conv)
        client = AgentClient(namespace, api_key)
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
                if run_slot:
                    await limits.release_run(user_id, run_slot)
                await client.aclose()
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
                if run_slot:
                    await limits.release_run(user_id, run_slot)
                await client.aclose()
                yield sse("error", {"code": "invalid_target", "detail": "未找到对应的用户消息"})
                return

            target_msg = ordered[target_idx]
            user_msg = ordered[preceding_idx]
            history = _history_from_messages(ordered[:preceding_idx])

            delete_ids = {m.id for m in ordered[target_idx:]}
            if target_msg.run_id:
                for m in ordered:
                    if m.role == "tool" and m.run_id == target_msg.run_id:
                        delete_ids.add(m.id)
            if delete_ids:
                await db.execute(delete(Message).where(Message.id.in_(delete_ids)))
                if conv.summary_cursor_msg_id and conv.summary_cursor_msg_id in delete_ids:
                    conv.rolling_summary = None
                    conv.summary_cursor_msg_id = None

            prompt_payload = user_msg.tool_payload or {}
            file_ids: list[uuid.UUID] = []
            for att in prompt_payload.get("attachments") or []:
                if isinstance(att, dict) and att.get("id"):
                    try:
                        file_ids.append(uuid.UUID(str(att["id"])))
                    except ValueError:
                        pass
            skill_names = [str(s) for s in (prompt_payload.get("skills") or []) if str(s).strip()]

            turn_ctx = await _prepare_turn_context(
                db, user, conv, file_ids, skill_names, query_text=user_msg.content
            )

            old_thread_id = conv.thread_id
            conv.thread_id = str(uuid.uuid4())

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

            # Delete old checkpoint ONLY after DB commit succeeds
            if old_thread_id:
                try:
                    await client.delete_thread(old_thread_id)
                except AgentError:
                    pass

            await usage.record_message(db, user_id)
            yield sse(
                "message.created",
                {
                    "user_message_id": str(user_msg.id),
                    "assistant_message_id": str(assistant.id),
                    "replaced_message_id": str(target_message_id),
                },
            )

            sup, q, run_id = await _launch_supervised_turn(
                db,
                client,
                conv,
                user,
                assistant,
                user_msg.id,
                user_msg.content,
                turn_ctx,
                conversation_history=history or None,
                model_route=model_route,
                max_seconds=max_seconds,
                run_slot=run_slot,
                idempotency_key=idempotency_key,
            )
            run_slot_handed_off = True
            yield sse("run.started", {"run_id": run_id})
        except AgentError as exc:
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            conv.pending_control = None
            await db.commit()
            if run_slot and not run_slot_handed_off:
                await limits.release_run(user_id, run_slot)
            await client.aclose()
            yield sse("error", {"code": "agent_error", "status": exc.status_code, "detail": exc.detail})
            return
        except Exception as exc:
            logger.exception("chat regenerate failed")
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            conv.pending_control = None
            await db.commit()
            if run_slot and not run_slot_handed_off:
                await limits.release_run(user_id, run_slot)
            await client.aclose()
            yield sse("error", {"code": "internal_error", "detail": str(exc)})
            return

    if sup is not None and q is not None:
        async for ev in run_supervisor.iter_subscriber_queue(sup, q):
            yield ev


async def stream_edit(
    conv_id: uuid.UUID,
    user_id: uuid.UUID,
    namespace: str,
    api_key: str,
    target_message_id: uuid.UUID,
    content: str,
    file_ids: list[uuid.UUID] | None = None,
    skill_names: list[str] | None = None,
    model_route: str = "auto",
    max_seconds: int | None = None,
    run_slot: str | None = None,
    idempotency_key: str | None = None,
) -> AsyncIterator[dict]:
    sup: run_supervisor.SupervisedRun | None = None
    q: asyncio.Queue[dict[str, Any] | None] | None = None
    run_slot_handed_off = False

    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        user = await db.get(User, user_id)
        if conv is None or user is None:
            if run_slot:
                await limits.release_run(user_id, run_slot)
            yield sse("error", {"code": "not_found"})
            return
        now = datetime.now(timezone.utc)
        claimed = await db.execute(
            update(Conversation)
            .where(Conversation.id == conv_id, Conversation.active_run_id.is_(None))
            .values(active_run_id="pending", active_run_status="starting", pending_control=None, last_message_at=now)
        )
        await db.commit()
        if not claimed.rowcount:
            if run_slot:
                await limits.release_run(user_id, run_slot)
            yield sse("error", {"code": "run_in_progress", "detail": "当前会话有进行中的任务"})
            return
        await db.refresh(conv)
        client = AgentClient(namespace, api_key)
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
                if run_slot:
                    await limits.release_run(user_id, run_slot)
                await client.aclose()
                yield sse("error", {"code": "invalid_target", "detail": "未找到可编辑的用户消息"})
                return

            history = _history_from_messages(ordered[:target_idx])
            delete_ids = {m.id for m in ordered[target_idx:]}
            if delete_ids:
                await db.execute(delete(Message).where(Message.id.in_(delete_ids)))
                if conv.summary_cursor_msg_id and conv.summary_cursor_msg_id in delete_ids:
                    conv.rolling_summary = None
                    conv.summary_cursor_msg_id = None

            turn_ctx = await _prepare_turn_context(db, user, conv, file_ids, skill_names, query_text=content)

            old_thread_id = conv.thread_id
            conv.thread_id = str(uuid.uuid4())

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=content,
                tool_payload=turn_ctx["user_payload"],
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
            await db.flush()
            attached_fids = turn_ctx.get("attached_file_ids") or []
            if attached_fids:
                await db.execute(
                    update(ConversationFile)
                    .where(
                        ConversationFile.id.in_(attached_fids),
                        ConversationFile.conversation_id == conv.id,
                        ConversationFile.user_id == user.id,
                        ConversationFile.message_id.is_(None),
                    )
                    .values(message_id=user_msg.id)
                )
            conv.plan = None
            conv.last_message_at = datetime.now(timezone.utc)
            await db.commit()

            if old_thread_id:
                try:
                    await client.delete_thread(old_thread_id)
                except AgentError:
                    pass

            await usage.record_message(db, user_id)
            yield sse(
                "message.created",
                {
                    "user_message_id": str(user_msg.id),
                    "assistant_message_id": str(assistant.id),
                    "replaced_message_id": str(target_message_id),
                },
            )

            sup, q, run_id = await _launch_supervised_turn(
                db,
                client,
                conv,
                user,
                assistant,
                user_msg.id,
                content,
                turn_ctx,
                conversation_history=history or None,
                model_route=model_route,
                max_seconds=max_seconds,
                run_slot=run_slot,
                idempotency_key=idempotency_key,
            )
            run_slot_handed_off = True
            yield sse("run.started", {"run_id": run_id})
        except AgentError as exc:
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            conv.pending_control = None
            await db.commit()
            if run_slot and not run_slot_handed_off:
                await limits.release_run(user_id, run_slot)
            await client.aclose()
            yield sse("error", {"code": "agent_error", "status": exc.status_code, "detail": exc.detail})
            return
        except Exception as exc:
            logger.exception("chat edit failed")
            if assistant is not None:
                assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            conv.pending_control = None
            await db.commit()
            if run_slot and not run_slot_handed_off:
                await limits.release_run(user_id, run_slot)
            await client.aclose()
            yield sse("error", {"code": "internal_error", "detail": str(exc)})
            return

    if sup is not None and q is not None:
        async for ev in run_supervisor.iter_subscriber_queue(sup, q):
            yield ev


async def stream_reconnect(
    conv_id: uuid.UUID,
    namespace: str,
    api_key: str,
    run_id: str,
    *,
    last_event_id: str | None = None,
    max_seconds: int | None = None,
) -> AsyncIterator[dict]:
    """Strictly READ-ONLY multi-device / refresh reconnect stream.

    1. Never mutates DB or double-bills credits (Single-Writer RunSupervisor owns persistence).
    2. Emits an atomic ``run.snapshot`` so refreshing tabs or Device B never duplicate partial tokens,
       reasoning blocks, or tool calls.
    """
    assistant_id_str = ""
    assistant_status = ""
    assistant_content = ""
    assistant_payload: dict[str, Any] = {}
    conv_plan: dict[str, Any] | None = None
    conv_pending_control: dict[str, Any] | None = None

    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        result = await db.execute(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.run_id == run_id,
                Message.role == "assistant",
            )
        )
        assistant = result.scalars().first()
        if assistant is None:
            yield sse("error", {"code": "run_not_found", "detail": "未找到对应的运行记录"})
            return
        assistant_id_str = str(assistant.id)
        assistant_status = str(assistant.status or "")
        assistant_content = assistant.content or ""
        assistant_payload = dict(assistant.tool_payload or {})
        conv_plan = conv.plan
        conv_pending_control = conv.pending_control

    yield sse("run.reconnected", {"run_id": run_id, "assistant_message_id": assistant_id_str})

    # Fast path A: active RunSupervisor in this process -> atomic snapshot + live queue fan-out
    sup = run_supervisor.get_supervisor(run_id)
    if sup is not None:
        q = sup.add_subscriber(replay_seed=False)
        yield sup.build_snapshot_event()
        async for ev in run_supervisor.iter_subscriber_queue(sup, q):
            yield ev
        return

    # Fast path B: run already finished in DB -> emit snapshot + terminal event immediately
    if assistant_status in ("completed", "failed", "cancelled"):
        term_ev = TERMINAL_STATUSES.get(assistant_status, "run.completed")
        yield sse(
            "run.snapshot",
            {
                "run_id": run_id,
                "conversation_id": str(conv_id),
                "assistant_message_id": assistant_id_str,
                "status": assistant_status,
                "output": assistant_content,
                "reasoning": assistant_payload.get("reasoning") or [],
                "plan": conv_plan or assistant_payload.get("plan"),
                "artifacts": assistant_payload.get("artifacts") or [],
                "pending_control": None,
                "last_event_id": "0-0",
            },
        )
        yield sse(
            term_ev,
            {
                "output": assistant_content,
                "usage": assistant_payload.get("usage"),
                "plan": conv_plan or assistant_payload.get("plan"),
                "reasoning": assistant_payload.get("reasoning"),
                "artifacts": assistant_payload.get("artifacts"),
            },
        )
        return

    # Path C: Run is alive on agent-worker (e.g., handled by another server worker) ->
    # read-only passthrough with snapshot from agent-api (no DB writes!)
    client = AgentClient(namespace, api_key)
    try:
        include_snap = not bool(last_event_id)
        async for ev_name, payload, ev_id in client.stream_events_with_id(
            run_id,
            last_event_id=last_event_id,
            include_snapshot=include_snap,
        ):
            if ev_name == "run.snapshot":
                payload = dict(payload)
                payload.setdefault("assistant_message_id", assistant_id_str)
                if not payload.get("pending_control") and isinstance(payload.get("pending_controls"), list):
                    ctls = payload["pending_controls"]
                    payload["pending_control"] = ctls[0] if ctls else conv_pending_control
            yield sse(ev_name, payload, event_id=ev_id)
            if ev_name in TERMINAL_EVENTS:
                return
    except AgentError as exc:
        yield sse("error", {"code": "agent_error", "status": exc.status_code, "detail": exc.detail})
    finally:
        await client.aclose()
