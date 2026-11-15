import json
from collections.abc import AsyncIterator

import httpx


async def iter_sse(response: httpx.Response) -> AsyncIterator[tuple[str, dict]]:
    """Parse an SSE stream, skipping comment/keepalive lines.

    Yields (event_name, payload). The event name prefers the payload's own
    `type` field when present, falling back to the SSE `event:` field.
    """
    event_type = "message"
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
                yield name, payload
            event_type = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
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
        yield payload.get("event") or payload.get("type") or event_type, payload