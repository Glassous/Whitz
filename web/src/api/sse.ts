import { getHost } from "../host";
import { ApiError, getAccessToken, handleUnauthorized, isAccessTokenExpiringSoon, tryRefresh } from "./client";

export interface SSEEvent {
  id?: string | null;
  event: string;
  data: Record<string, unknown>;
}

function parseBlock(block: string): SSEEvent | null {
  let eventType = "";
  let eventId: string | null = null;
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith("id:")) {
      const parsedId = line.slice(3).trim();
      if (parsedId) eventId = parsedId;
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
  return { id: eventId, event: name, data };
}

async function readWithTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  idleTimeoutMs: number,
  signal?: AbortSignal,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (idleTimeoutMs <= 0) return reader.read();
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          const err = new Error("SSE stream idle timeout");
          err.name = "SSEIdleTimeoutError";
          reject(err);
        }, idleTimeoutMs);
        signal?.addEventListener(
          "abort",
          () => {
            if (timer) clearTimeout(timer);
          },
          { once: true },
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function* readSSE(
  stream: ReadableStream<Uint8Array>,
  idleTimeoutMs = 45_000,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await readWithTimeout(reader, idleTimeoutMs, signal);
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
    try {
      await reader.cancel();
    } catch {
      /* ignore */
    }
    reader.releaseLock();
  }
}

export async function* streamSSE(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  extraHeaders: Record<string, string> = {},
  idleTimeoutMs = 45_000,
): AsyncGenerator<SSEEvent> {
  if (isAccessTokenExpiringSoon()) {
    await tryRefresh();
  }
  const headers: Record<string, string> = {
    ...extraHeaders,
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  const host = getHost();
  let resp = await fetch(host.transport.baseUrl + path, {
    method: "POST",
    headers,
    credentials: host.transport.credentials,
    body: JSON.stringify(body),
    signal,
  });

  if (resp.status === 401) {
    if (await tryRefresh()) {
      headers["Authorization"] = "Bearer " + getAccessToken();
      resp = await fetch(host.transport.baseUrl + path, {
        method: "POST",
        headers,
        credentials: host.transport.credentials,
        body: JSON.stringify(body),
        signal,
      });
    } else {
      handleUnauthorized();
    }
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

  yield* readSSE(resp.body, idleTimeoutMs, signal);
}

export async function* streamSSEGet(
  path: string,
  signal?: AbortSignal,
  extraHeaders: Record<string, string> = {},
  idleTimeoutMs = 45_000,
): AsyncGenerator<SSEEvent> {
  if (isAccessTokenExpiringSoon()) {
    await tryRefresh();
  }
  const headers: Record<string, string> = { ...extraHeaders, Accept: "text/event-stream" };
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;
  const host = getHost();
  let resp = await fetch(host.transport.baseUrl + path, {
    method: "GET",
    headers,
    credentials: host.transport.credentials,
    signal,
  });
  if (resp.status === 401) {
    if (await tryRefresh()) {
      headers["Authorization"] = "Bearer " + getAccessToken();
      resp = await fetch(host.transport.baseUrl + path, {
        method: "GET",
        headers,
        credentials: host.transport.credentials,
        signal,
      });
    } else {
      handleUnauthorized();
    }
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
  yield* readSSE(resp.body, idleTimeoutMs, signal);
}
