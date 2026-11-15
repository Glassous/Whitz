import { ApiError, getAccessToken, tryRefresh } from "./client";

export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

function parseBlock(block: string): SSEEvent | null {
  let eventType = "";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(dataStr) as Record<string, unknown>;
  } catch {
    data = { raw: dataStr };
  }
  const name = eventType || (typeof data.type === "string" ? data.type : "message");
  return { event: name, data };
}

async function* readSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      for (;;) {
        const match = /\r?\n\r?\n/.exec(buffer);
        if (!match) break;
        const block = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const ev = parseBlock(block);
        if (ev) yield ev;
      }
    }
    if (buffer.trim()) {
      const ev = parseBlock(buffer);
      if (ev) yield ev;
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* streamSSE(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let resp = await fetch("/api" + path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  if (resp.status === 401 && (await tryRefresh())) {
    headers["Authorization"] = "Bearer " + getAccessToken();
    resp = await fetch("/api" + path, { method: "POST", headers, body: JSON.stringify(body), signal });
  }

  if (!resp.ok || !resp.body) {
    let detail: unknown = resp.statusText;
    try {
      detail = await resp.json();
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail);
  }

  yield* readSSE(resp.body);
}

export async function* streamSSEGet(path: string, signal?: AbortSignal): AsyncGenerator<SSEEvent> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  let resp = await fetch("/api" + path, { method: "GET", headers, signal });
  if (resp.status === 401 && (await tryRefresh())) {
    headers["Authorization"] = "Bearer " + getAccessToken();
    resp = await fetch("/api" + path, { method: "GET", headers, signal });
  }
  if (!resp.ok || !resp.body) {
    throw new ApiError(resp.status, resp.statusText);
  }
  yield* readSSE(resp.body);
}