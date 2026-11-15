import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.sse import iter_sse


class HermesError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Hermes {status_code}: {detail}")


class HermesClient:
    """Client for one user's profile on the multiplexed Hermes gateway."""

    def __init__(self, profile: str, api_key: str) -> None:
        self.profile = profile
        self.base = f"{get_settings().hermes_base_url}/p/{profile}"
        self._client = httpx.AsyncClient(
            base_url=self.base,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60.0),
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise HermesError(503, "agent_unreachable") from exc
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise HermesError(resp.status_code, detail)
        return resp

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def capabilities(self) -> dict:
        return (await self._request("GET", "/v1/capabilities")).json()

    async def toolsets(self) -> list:
        return (await self._request("GET", "/v1/toolsets")).json()

    async def create_session(self, title: str = "新对话") -> dict:
        # Hermes enforces unique session titles per profile, so keep the display title
        # in Postgres and create the Hermes-side session under a unique variant.
        unique_title = f"{title} · {uuid.uuid4().hex[:6]}"
        data = (await self._request("POST", "/api/sessions", json={"title": unique_title})).json()
        if isinstance(data, dict) and not data.get("id"):
            session = data.get("session")
            if isinstance(session, dict):
                data = {**data, "id": session.get("id") or session.get("session_id")}
        return data

    async def patch_session(self, session_id: str, title: str) -> dict:
        return (await self._request("PATCH", f"/api/sessions/{session_id}", json={"title": title})).json()

    async def delete_session(self, session_id: str) -> None:
        await self._request("DELETE", f"/api/sessions/{session_id}")

    async def session_messages(self, session_id: str) -> list:
        data = (await self._request("GET", f"/api/sessions/{session_id}/messages")).json()
        if isinstance(data, dict):
            for key in ("messages", "data", "items"):
                if isinstance(data.get(key), list):
                    return data[key]
            return []
        return data

    async def create_run(self, input_text: str, session_id: str, idempotency_key: str) -> dict:
        resp = await self._request(
            "POST",
            "/v1/runs",
            json={"input": input_text, "session_id": session_id},
            headers={"Idempotency-Key": idempotency_key},
        )
        return resp.json()

    async def get_run(self, run_id: str) -> dict:
        return (await self._request("GET", f"/v1/runs/{run_id}")).json()

    async def stop_run(self, run_id: str) -> dict:
        return (await self._request("POST", f"/v1/runs/{run_id}/stop")).json()

    async def approve(self, run_id: str, request_id: str, execution_generation: int, choice: str) -> dict:
        return (
            await self._request(
                "POST",
                f"/v1/runs/{run_id}/approval",
                json={"request_id": request_id, "execution_generation": execution_generation, "choice": choice},
            )
        ).json()

    async def clarify(self, run_id: str, request_id: str, execution_generation: int, answer: str) -> dict:
        return (
            await self._request(
                "POST",
                f"/v1/runs/{run_id}/clarify",
                json={"request_id": request_id, "execution_generation": execution_generation, "answer": answer},
            )
        ).json()

    async def stream_run_events(self, run_id: str) -> AsyncIterator[tuple[str, dict]]:
        try:
            async with self._client.stream(
                "GET", f"/v1/runs/{run_id}/events", timeout=httpx.Timeout(30.0, read=None)
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    try:
                        detail = resp.json()
                    except Exception:
                        detail = resp.text
                    raise HermesError(resp.status_code, detail)
                async for event in iter_sse(resp):
                    yield event
        except httpx.HTTPError as exc:
            raise HermesError(503, "agent_unreachable") from exc