import { gatewayApiKey, gatewayBaseUrl } from "../runtime/hermesRuntime";
import type { WorkEvent } from "../../shared/work-types";

export class LocalHermesClient {
  private base: string;
  private key: string;

  constructor(base?: string, key?: string) {
    this.base = (base ?? gatewayBaseUrl()).replace(/\/+$/, "");
    this.key = key ?? gatewayApiKey();
    if (!this.base) throw new Error("本地运行时尚未启动");
  }

  private async request<T>(method: string, path: string, body?: unknown, timeoutMs = 60_000): Promise<T> {
    const resp = await fetch(`${this.base}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.key}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await resp.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!resp.ok) {
      const detail = typeof data === "object" && data && "detail" in data ? (data as Record<string, unknown>).detail : data;
      throw new Error(`Hermes ${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
    return data as T;
  }

  async createSession(title: string): Promise<string> {
    const unique = `${title || "本地对话"} · ${Math.random().toString(16).slice(2, 8)}`;
    const data = await this.request<Record<string, unknown>>("POST", "/api/sessions", { title: unique });
    const nested = data.session as Record<string, unknown> | undefined;
    return String(data.id ?? nested?.id ?? (data as Record<string, unknown>).session_id ?? "");
  }

  async createRun(input: string, sessionId: string): Promise<string> {
    const data = await this.request<Record<string, unknown>>(
      "POST",
      "/v1/runs",
      { input, session_id: sessionId },
      120_000,
    );
    return String(data.run_id ?? data.id ?? "");
  }

  async getRun(runId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>("GET", `/v1/runs/${runId}`, undefined, 20_000);
  }

  async stopRun(runId: string): Promise<void> {
    await this.request("POST", `/v1/runs/${runId}/stop`, {}, 20_000);
  }

  async approve(runId: string, requestId: string, generation: number, choice: string): Promise<void> {
    await this.request(
      "POST",
      `/v1/runs/${runId}/approval`,
      { request_id: requestId, execution_generation: generation, choice },
      30_000,
    );
  }

  async clarify(runId: string, requestId: string, generation: number, answer: string): Promise<void> {
    await this.request(
      "POST",
      `/v1/runs/${runId}/clarify`,
      { request_id: requestId, execution_generation: generation, answer },
      30_000,
    );
  }

  async *streamRun(runId: string, signal: AbortSignal): AsyncGenerator<WorkEvent> {
    const resp = await fetch(`${this.base}/v1/runs/${runId}/events`, {
      headers: { Authorization: `Bearer ${this.key}`, Accept: "text/event-stream" },
      signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`Hermes 事件流不可用（${resp.status}）`);
    }
    const reader = resp.body.getReader();
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
          const parsed = parseBlock(block);
          if (parsed) yield parsed;
        }
      }
      if (buffer.trim()) {
        const parsed = parseBlock(buffer);
        if (parsed) yield parsed;
      }
    } finally {
      reader.releaseLock();
    }
  }
}

function parseBlock(block: string): WorkEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    data = { raw };
  }
  return { event: event || (typeof data.type === "string" ? data.type : "message"), data };
}
