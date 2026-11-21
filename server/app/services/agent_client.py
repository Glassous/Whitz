from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.sse import iter_sse


class AgentError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Agent {status_code}: {detail}")


class AgentClient:
    """Async HTTP + SSE client for the standalone LangGraph agent service."""

    def __init__(
        self,
        namespace: str | None = None,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        internal_token: str | None = None,
    ) -> None:
        settings = get_settings()
        self.namespace = namespace or ""
        self.api_key = api_key or ""
        self.base = (base_url or settings.agent_base_url).rstrip("/")
        token = (internal_token if internal_token is not None else settings.agent_internal_token).strip()
        headers: dict[str, str] = {}
        if token:
            headers["X-Agent-Token"] = token
        if self.namespace:
            headers["X-Whitz-Namespace"] = self.namespace
        self._client = httpx.AsyncClient(
            base_url=self.base,
            headers=headers,
            timeout=httpx.Timeout(60.0),
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentError(503, "agent_unreachable") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise AgentError(resp.status_code, detail)
        return resp

    async def health_info(self) -> dict[str, Any]:
        try:
            resp = await self._client.get("/health")
            if resp.status_code != 200:
                return {"ready": False, "status": "unhealthy"}
            data = resp.json()
            if isinstance(data, dict):
                return {"ready": True, **data}
            return {"ready": True, "status": "ok"}
        except Exception:
            return {"ready": False, "status": "unreachable"}

    async def health(self) -> bool:
        info = await self.health_info()
        return bool(info.get("ready"))

    async def topology(self) -> dict[str, Any]:
        return (await self._request("GET", "/v1/graph/topology")).json()

    async def create_run(
        self,
        *,
        thread_id: str,
        user_id: str,
        agent_namespace: str,
        agent_api_key: str,
        conversation_id: str,
        input_text: str,
        conversation_kind: str = "side",
        assistant_name: str = "Whitz",
        rolling_summary: str | None = None,
        cross_chat_context: str | None = None,
        instructions: str | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        model_route: str = "auto",
        attachments: list[dict[str, Any]] | None = None,
        skills: list[dict[str, Any]] | None = None,
        requested_skills: list[str] | None = None,
        persona: str = "",
        profile_context: str | None = None,
        timezone: str | None = None,
        memory_enabled: bool = False,
        memory_require_confirm: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "thread_id": thread_id,
            "user_id": user_id,
            "agent_namespace": agent_namespace,
            "agent_api_key": agent_api_key,
            "conversation_id": conversation_id,
            "conversation_kind": conversation_kind or "side",
            "assistant_name": (assistant_name or "").strip() or "Whitz",
            "input": input_text,
            "model_route": model_route or "auto",
            "persona": persona or "",
            "timezone": (timezone or "").strip() or "Asia/Shanghai",
            "memory_enabled": bool(memory_enabled),
            "memory_require_confirm": bool(memory_require_confirm),
        }
        if rolling_summary:
            payload["rolling_summary"] = rolling_summary
        if cross_chat_context:
            payload["cross_chat_context"] = cross_chat_context
        if instructions:
            payload["instructions"] = instructions
        if conversation_history:
            payload["conversation_history"] = conversation_history
        if attachments:
            payload["attachments"] = attachments
        if skills:
            payload["skills"] = skills
        if requested_skills:
            payload["requested_skills"] = requested_skills
        if profile_context:
            payload["profile_context"] = profile_context

        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp = await self._request("POST", "/v1/runs", json=payload, headers=headers)
        return resp.json()

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return (await self._request("GET", f"/v1/runs/{run_id}")).json()

    async def resume_run(
        self,
        run_id: str,
        *,
        kind: str,
        request_id: str | None = None,
        execution_generation: int | None = None,
        choice: str | None = None,
        answer: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": kind}
        if request_id is not None:
            payload["request_id"] = request_id
        if execution_generation is not None:
            payload["execution_generation"] = execution_generation
        if choice is not None:
            payload["choice"] = choice
        if answer is not None:
            payload["answer"] = answer
        return (await self._request("POST", f"/v1/runs/{run_id}/resume", json=payload)).json()

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return (await self._request("POST", f"/v1/runs/{run_id}/cancel")).json()

    async def stream_events(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        headers: dict[str, str] = {}
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        try:
            async with self._client.stream(
                "GET",
                f"/v1/runs/{run_id}/events",
                headers=headers,
                timeout=httpx.Timeout(30.0, read=None),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    try:
                        detail = resp.json()
                    except Exception:
                        detail = resp.text
                    raise AgentError(resp.status_code, detail)
                async for event in iter_sse(resp):
                    yield event
        except httpx.HTTPError as exc:
            raise AgentError(503, "agent_unreachable") from exc

    async def delete_thread(self, thread_id: str) -> None:
        if not thread_id:
            return
        try:
            resp = await self._client.delete(f"/v1/threads/{thread_id}")
            if resp.status_code >= 400 and resp.status_code != 404:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise AgentError(resp.status_code, detail)
        except httpx.HTTPError as exc:
            raise AgentError(503, "agent_unreachable") from exc
