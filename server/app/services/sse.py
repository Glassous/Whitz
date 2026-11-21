import json
from collections.abc import AsyncIterator

import httpx


async def iter_sse_with_id(response: httpx.Response) -> AsyncIterator[tuple[str, dict, str | None]]:
    """Parse an SSE stream preserving ``id:`` lines, skipping comments/keepalives.

    Yields ``(event_name, payload, event_id)``.
    """
    event_type = "message"
    event_id: str | None = None
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith(":"):
            continue
        if line == "":
            if data_lines:
                raw = "\n".join(data_lines)
                try:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        payload = {"value": payload}
                except json.JSONDecodeError:
                    payload = {"raw": raw}
                name = payload.get("event") or payload.get("type") or event_type
                yield name, payload, event_id
            event_type = "message"
            event_id = None
            data_lines = []
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("id:"):
            raw_id = line[len("id:"):].strip()
            event_id = raw_id or None
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())
    if data_lines:
        raw = "\n".join(data_lines)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                payload = {"value": payload}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        yield payload.get("event") or payload.get("type") or event_type, payload, event_id


async def iter_sse(response: httpx.Response) -> AsyncIterator[tuple[str, dict]]:
    """Backward-compatible wrapper yielding ``(event_name, payload)``."""
    async for name, payload, _event_id in iter_sse_with_id(response):
        yield name, payload
