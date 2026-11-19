import { opencodeAuthHeader, opencodeBaseUrl } from "../runtime/opencodeRuntime";
import type { LiveProviderPayload } from "../runtime/opencodeConfig";
import type { WorkSkillItem } from "../../shared/work-types";

export interface OpenCodeEvent {
  type: string;
  properties: Record<string, unknown>;
}

export class OpenCodeClient {
  private base: string;

  constructor(base?: string) {
    this.base = (base ?? opencodeBaseUrl()).replace(/\/+$/, "");
    if (!this.base) throw new Error("OpenCode 本地服务尚未就绪");
  }

  private withDir(route: string, directory?: string | null): string {
    if (!directory) return `${this.base}${route}`;
    const sep = route.includes("?") ? "&" : "?";
    return `${this.base}${route}${sep}directory=${encodeURIComponent(directory)}`;
  }

  private async request<T>(
    method: string,
    route: string,
    options?: {
      directory?: string | null;
      body?: unknown;
      timeoutMs?: number;
    },
  ): Promise<T> {
    const url = this.withDir(route, options?.directory);
    const resp = await fetch(url, {
      method,
      headers: {
        ...opencodeAuthHeader(),
        ...(options?.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: AbortSignal.timeout(options?.timeoutMs ?? 60_000),
    });
    const text = await resp.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!resp.ok) {
      const detail =
        typeof data === "object" && data && "detail" in data
          ? (data as Record<string, unknown>).detail
          : typeof data === "object" && data && "message" in data
            ? (data as Record<string, unknown>).message
            : data;
      throw new Error(`OpenCode ${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
    return data as T;
  }

  async createSession(title: string, directory?: string | null): Promise<string> {
    const data = await this.request<Record<string, unknown>>("POST", "/session", {
      directory,
      body: { title: title || "新的工作区对话" },
    });
    return String(data.id ?? "");
  }

  async promptAsync(
    sessionId: string,
    directory: string | null,
    payload: {
      messageID?: string;
      parts: Array<{ type: "text"; text: string }>;
      model?: { providerID: string; modelID: string };
      system?: string;
      agent?: string;
    },
  ): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/prompt_async`, {
      directory,
      body: payload,
      timeoutMs: 30_000,
    });
  }

  async abortSession(sessionId: string, directory?: string | null): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/abort`, {
      directory,
      timeoutMs: 15_000,
    });
  }

  async getTodos(sessionId: string, directory?: string | null): Promise<Array<Record<string, unknown>>> {
    const data = await this.request<unknown>("GET", `/session/${encodeURIComponent(sessionId)}/todo`, {
      directory,
      timeoutMs: 15_000,
    });
    return Array.isArray(data) ? (data as Array<Record<string, unknown>>) : [];
  }

  async replyPermission(
    requestId: string,
    directory: string | null,
    reply: "once" | "always" | "reject",
    message?: string,
  ): Promise<void> {
    await this.request("POST", `/permission/${encodeURIComponent(requestId)}/reply`, {
      directory,
      body: message ? { reply, message } : { reply },
      timeoutMs: 20_000,
    });
  }

  async replyQuestion(requestId: string, directory: string | null, answers: string[][]): Promise<void> {
    await this.request("POST", `/question/${encodeURIComponent(requestId)}/reply`, {
      directory,
      body: { answers },
      timeoutMs: 20_000,
    });
  }

  async rejectQuestion(requestId: string, directory: string | null): Promise<void> {
    await this.request("POST", `/question/${encodeURIComponent(requestId)}/reject`, {
      directory,
      timeoutMs: 20_000,
    });
  }

  async listProviders(directory?: string | null): Promise<LiveProviderPayload> {
    return this.request<LiveProviderPayload>("GET", "/provider", { directory, timeoutMs: 15_000 });
  }

  async listSkills(directory?: string | null): Promise<WorkSkillItem[]> {
    const data = await this.request<unknown>("GET", "/skill", { directory, timeoutMs: 15_000 });
    const list = Array.isArray(data) ? data : [];
    return list
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        name: String(x.name ?? ""),
        description: String(x.description ?? ""),
        source: String(x.location ?? "opencode"),
        enabled: true,
      }))
      .filter((s) => s.name);
  }

  async setAuth(providerId: string, apiKey: string): Promise<void> {
    await this.request("PUT", `/auth/${encodeURIComponent(providerId)}`, {
      body: { type: "api", key: apiKey },
      timeoutMs: 15_000,
    });
  }

  async removeAuth(providerId: string): Promise<void> {
    await this.request("DELETE", `/auth/${encodeURIComponent(providerId)}`, { timeoutMs: 15_000 });
  }

  async *streamEvents(directory: string | null, signal: AbortSignal): AsyncGenerator<OpenCodeEvent> {
    const url = this.withDir("/event", directory);
    const resp = await fetch(url, {
      headers: {
        ...opencodeAuthHeader(),
        Accept: "text/event-stream",
      },
      signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`OpenCode 事件流不可用（${resp.status}）`);
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
          const parsed = parseSseEvent(block);
          if (parsed) yield parsed;
        }
      }
    } finally {
      reader.releaseLock();
    }
  }
}

function parseSseEvent(block: string): OpenCodeEvent | null {
  const dataLines: string[] = [];
  for (const raw of block.split(/\r?\n/)) {
    if (!raw || raw.startsWith(":")) continue;
    if (raw.startsWith("data:")) dataLines.push(raw.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  const text = dataLines.join("\n");
  try {
    const obj = JSON.parse(text) as Record<string, unknown>;
    const type = typeof obj.type === "string" ? obj.type : "";
    if (!type) return null;
    const properties =
      obj.properties && typeof obj.properties === "object" && !Array.isArray(obj.properties)
        ? (obj.properties as Record<string, unknown>)
        : {};
    return { type, properties };
  } catch {
    return null;
  }
}
