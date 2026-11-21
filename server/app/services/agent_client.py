from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.sse import iter_sse_with_id


class AgentError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Agent {status_code}: {detail}")


# Shared process-level connection pools keyed by base URL so AgentClient instances reuse sockets.
_SHARED_CLIENTS: dict[str, httpx.AsyncClient] = {}


def _get_shared_client(base_url: str) -> httpx.AsyncClient:
    client = _SHARED_CLIENTS.get(base_url)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(30.0, connect=8.0),
            limits=httpx.Limits(max_connections=128, max_keepalive_connections=32, keepalive_expiry=45.0),
            trust_env=False,
        )
        _SHARED_CLIENTS[base_url] = client
    return client


async def aclose_shared_agent_clients() -> None:
    for client in list(_SHARED_CLIENTS.values()):
        if not client.is_closed:
            try:
                await client.aclose()
            except Exception:
                pass
    _SHARED_CLIENTS.clear()


class AgentClient:
    """Async HTTP + SSE client for the standalone LangGraph agent service (pooled + retrying)."""

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
        self._headers: dict[str, str] = {}
        if token:
            self._headers["X-Agent-Token"] = token
        if self.namespace:
            self._headers["X-Whitz-Namespace"] = self.namespace
        self._client = _get_shared_client(self.base)

    async def aclose(self) -> None:
        # Shared pool is closed centrally on server shutdown via aclose_shared_agent_clients().
        return None

    def _merge_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        if not extra:
            return dict(self._headers)
        merged = dict(self._headers)
        merged.update(extra)
        return merged

    async def _request(
        self,
        method: str,
        path: str,
        *,
        retry_transient: bool = False,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        req_headers = self._merge_headers(headers)
        attempts = 3 if retry_transient else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = await self._client.request(method, path, headers=req_headers, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise AgentError(503, "agent_unreachable") from exc
            if resp.status_code in (502, 503, 504) and attempt + 1 < attempts:
                await asyncio.sleep(0.25 * (2**attempt))
                continue
            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise AgentError(resp.status_code, detail)
            return resp
        raise AgentError(503, "agent_unreachable") from last_exc

    async def health_info(self) -> dict[str, Any]:
        try:
            resp = await self._client.get(
                "/health",
                headers=self._headers,
                timeout=httpx.Timeout(5.0, connect=3.0),
            )
            if resp.status_code != 200:
                return {"ready": False, "status": "unhealthy"}
            data = resp.json()
            if isinstance(data, dict):
                return {"ready": bool(data.get("ok", True)), **data}
            return {"ready": True, "status": "ok"}
        except Exception:
            return {"ready": False, "status": "unreachable"}

    async def health(self) -> bool:
        info = await self.health_info()
        return bool(info.get("ready"))

    async def topology(self) -> dict[str, Any]:
        return (await self._request("GET", "/v1/graph/topology", retry_transient=True)).json()

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
        ai_reactions_enabled: bool = True,
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
            "ai_reactions_enabled": bool(ai_reactions_enabled),
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
        resp = await self._request(
            "POST",
            "/v1/runs",
            json=payload,
            headers=headers,
            retry_transient=bool(idempotency_key),
        )
        return resp.json()

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return (await self._request("GET", f"/v1/runs/{run_id}", retry_transient=True)).json()

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

    async def stream_events_with_id(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        include_snapshot: bool = False,
    ) -> AsyncIterator[tuple[str, dict, str | None]]:
        headers = self._merge_headers({"Last-Event-ID": last_event_id} if last_event_id else None)
        params = {"include_snapshot": "true"} if include_snapshot else None
        try:
            # Agent-API sends SSE keepalive pings every 10s; a 45s read timeout catches half-open drops cleanly.
            async with self._client.stream(
                "GET",
                f"/v1/runs/{run_id}/events",
                headers=headers,
                params=params,
                timeout=httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=15.0),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    try:
                        detail = resp.json()
                    except Exception:
                        detail = resp.text
                    raise AgentError(resp.status_code, detail)
                async for ev_name, payload, ev_id in iter_sse_with_id(resp):
                    yield ev_name, payload, ev_id
        except httpx.HTTPError as exc:
            raise AgentError(503, "agent_unreachable") from exc

    async def stream_events(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        include_snapshot: bool = False,
    ) -> AsyncIterator[tuple[str, dict]]:
        async for ev_name, payload, _ev_id in self.stream_events_with_id(
            run_id,
            last_event_id=last_event_id,
            include_snapshot=include_snapshot,
        ):
            yield ev_name, payload

    async def delete_thread(self, thread_id: str) -> None:
        if not thread_id:
            return
        try:
            resp = await self._client.delete(f"/v1/threads/{thread_id}", headers=self._headers)
            if resp.status_code >= 400 and resp.status_code != 404:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise AgentError(resp.status_code, detail)
        except httpx.HTTPError as exc:
            raise AgentError(503, "agent_unreachable") from exc
