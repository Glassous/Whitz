import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.services.hermes import HermesClient, HermesError

logger = logging.getLogger("whitz.chat")

TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled", "run.interrupted"}
TERMINAL_STATUSES = {
    "completed": "run.completed",
    "failed": "run.failed",
    "cancelled": "run.cancelled",
    "interrupted": "run.interrupted",
}


def sse(name: str, payload: dict) -> dict:
    return {"event": name, "data": json.dumps(payload, ensure_ascii=False)}


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


class ChatPipeline:
    def __init__(
        self,
        db: AsyncSession,
        client: HermesClient,
        conv: Conversation,
        assistant: Message,
        run_id: str,
        started_at: float | None = None,
    ):
        self.db = db
        self.client = client
        self.conv = conv
        self.assistant = assistant
        self.run_id = run_id
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
        self.native_reasoning = False
        self.terminal = False
        if started_at is not None:
            self.started_at = started_at
        elif assistant.created_at is not None:
            self.started_at = assistant.created_at.timestamp() - 5
        else:
            self.started_at = 0.0

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
            self.assistant.tool_payload = payload
            await self.db.commit()
            self.last_flush = now

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
        if not self.reasoning and not self.plan:
            return
        payload = dict(self.assistant.tool_payload or {})
        if self.reasoning:
            payload["reasoning"] = self.reasoning
        if self.plan:
            payload["plan"] = self.plan
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
                {"tool": tool, "preview": preview, "error": error, "duration": duration,
                 "message_id": str(row.id) if row else None},
            )
            if tool == "todo_list":
                items = parse_todos(preview)
                if items is not None:
                    self.plan = {"items": items}
                    self.conv.plan = self.plan
                    await self.db.commit()
                    yield sse("plan.updated", self.plan)
            async for ev in self._sync_session():
                yield ev

        elif name in ("approval.request", "clarify.request"):
            request_id, generation = await self._control_ids(payload)
            self.assistant.status = "waiting"
            self.conv.active_run_status = "waiting_for_approval" if name == "approval.request" else "waiting_for_clarify"
            await self.db.commit()
            yield sse(
                name,
                {"request_id": request_id, "execution_generation": generation,
                 "tool": payload.get("tool"), "preview": payload.get("preview"), "detail": payload},
            )

        elif name == "run.completed":
            self.terminal = True
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
            if self.reasoning or self.plan:
                extra = dict(self.assistant.tool_payload or {})
                if self.reasoning:
                    extra["reasoning"] = self.reasoning
                if self.plan:
                    extra["plan"] = self.plan
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

    async def pump(self) -> AsyncIterator[dict]:
        try:
            async for name, payload in self.client.stream_run_events(self.run_id):
                async for ev in self.handle(name, payload):
                    yield ev
                if self.terminal:
                    break
        except HermesError as exc:
            if exc.status_code != 404:
                raise
        if self.terminal:
            return

        # Event replay expired or the stream closed early: reconcile via run status.
        for _ in range(900):
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

        yield sse("error", {"code": "run_timeout", "detail": "任务仍在后台执行，可稍后重新打开会话查看结果"})


async def stream_chat(conv_id: uuid.UUID, profile: str, api_key: str, content: str) -> AsyncIterator[dict]:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        client = HermesClient(profile, api_key)
        assistant = None
        try:
            if not conv.hermes_session_id:
                session = await client.create_session(conv.title)
                conv.hermes_session_id = str(session.get("id") or session.get("session_id") or "")
                await db.commit()

            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=content,
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
            yield sse("message.created", {"user_message_id": str(user_msg.id), "assistant_message_id": str(assistant.id)})

            run_started = time.time() - 2
            run = await client.create_run(content, conv.hermes_session_id, uuid.uuid4().hex)
            run_id = str(run.get("run_id") or run.get("id"))
            conv.active_run_id = run_id
            conv.active_run_status = "running"
            assistant.hermes_run_id = run_id
            await db.commit()
            yield sse("run.started", {"run_id": run_id})

            pipeline = ChatPipeline(db, client, conv, assistant, run_id, started_at=run_started)
            await pipeline.prepare()
            async for ev in pipeline.pump():
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


async def stream_reconnect(conv_id: uuid.UUID, profile: str, api_key: str, run_id: str) -> AsyncIterator[dict]:
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        if conv is None:
            yield sse("error", {"code": "not_found"})
            return
        result = await db.execute(
            select(Message).where(Message.conversation_id == conv.id, Message.hermes_run_id == run_id, Message.role == "assistant")
        )
        assistant = result.scalars().first()
        client = HermesClient(profile, api_key)
        try:
            if assistant is None:
                assistant = Message(conversation_id=conv.id, role="assistant", content="", status="streaming", hermes_run_id=run_id)
                db.add(assistant)
                await db.commit()
            yield sse("run.reconnected", {"run_id": run_id, "assistant_message_id": str(assistant.id)})
            pipeline = ChatPipeline(db, client, conv, assistant, run_id)
            pipeline.buffer = [assistant.content or ""]
            await pipeline.prepare()
            async for ev in pipeline.pump():
                yield ev
        except HermesError as exc:
            assistant.status = "failed"
            conv.active_run_id = None
            conv.active_run_status = None
            await db.commit()
            yield sse("error", {"code": "hermes_error", "status": exc.status_code, "detail": exc.detail})
        finally:
            await client.aclose()