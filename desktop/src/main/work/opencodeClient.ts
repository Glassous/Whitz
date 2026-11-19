import { opencodeAuthHeader, opencodeBaseUrl } from "../runtime/opencodeRuntime";
import type { LiveProviderPayload } from "../runtime/opencodeConfig";
import type {
  WorkAgentInfo,
  WorkCommandInfo,
  WorkLspStatus,
  WorkSessionDiffItem,
  WorkSkillItem,
} from "../../shared/work-types";

export type PromptPartInput =
  | { type: "text"; text: string }
  | { type: "file"; mime: string; filename?: string; url: string }
  | { type: "agent"; name: string };

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
      parts: PromptPartInput[];
      model?: { providerID: string; modelID: string };
      system?: string;
      agent?: string;
      variant?: string;
    },
  ): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/prompt_async`, {
      directory,
      body: payload,
      timeoutMs: 30_000,
    });
  }

  async runCommand(
    sessionId: string,
    directory: string | null,
    payload: {
      command: string;
      arguments: string;
      agent?: string;
      model?: string;
      variant?: string;
      parts?: Array<{ type: "file"; mime: string; filename?: string; url: string }>;
    },
  ): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/command`, {
      directory,
      body: payload,
      timeoutMs: 30_000,
    });
  }

  async runShell(
    sessionId: string,
    directory: string | null,
    payload: {
      agent: string;
      command: string;
      model?: { providerID: string; modelID: string };
    },
  ): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/shell`, {
      directory,
      body: payload,
      timeoutMs: 30_000,
    });
  }

  async forkSession(sessionId: string, directory: string | null, messageID?: string | null): Promise<string> {
    const data = await this.request<Record<string, unknown>>("POST", `/session/${encodeURIComponent(sessionId)}/fork`, {
      directory,
      body: messageID ? { messageID } : {},
      timeoutMs: 20_000,
    });
    return String(data.id ?? "");
  }

  async revertSession(sessionId: string, directory: string | null, messageID: string): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/revert`, {
      directory,
      body: { messageID },
      timeoutMs: 20_000,
    });
  }

  async unrevertSession(sessionId: string, directory: string | null): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/unrevert`, {
      directory,
      timeoutMs: 20_000,
    });
  }

  async summarizeSession(
    sessionId: string,
    directory: string | null,
    model: { providerID: string; modelID: string },
  ): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/summarize`, {
      directory,
      body: { providerID: model.providerID, modelID: model.modelID },
      timeoutMs: 60_000,
    });
  }

  async initSession(
    sessionId: string,
    directory: string | null,
    payload: { providerID: string; modelID: string; messageID: string },
  ): Promise<void> {
    await this.request("POST", `/session/${encodeURIComponent(sessionId)}/init`, {
      directory,
      body: payload,
      timeoutMs: 60_000,
    });
  }

  async getSessionDiff(sessionId: string, directory: string | null): Promise<WorkSessionDiffItem[]> {
    const data = await this.request<unknown>("GET", `/session/${encodeURIComponent(sessionId)}/diff`, {
      directory,
      timeoutMs: 15_000,
    });
    if (!Array.isArray(data)) return [];
    return data
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        file: String(x.file ?? ""),
        before: typeof x.before === "string" ? x.before : undefined,
        after: typeof x.after === "string" ? x.after : undefined,
        additions: typeof x.additions === "number" ? x.additions : undefined,
        deletions: typeof x.deletions === "number" ? x.deletions : undefined,
        status: (x.status === "added" || x.status === "deleted" || x.status === "modified"
          ? x.status
          : "modified") as WorkSessionDiffItem["status"],
      }))
      .filter((x) => x.file);
  }

  async listAgents(directory?: string | null): Promise<WorkAgentInfo[]> {
    const data = await this.request<unknown>("GET", "/agent", { directory, timeoutMs: 15_000 });
    const list = Array.isArray(data) ? data : [];
    return list
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        name: String(x.name ?? ""),
        description: typeof x.description === "string" ? x.description : undefined,
        mode: (x.mode === "primary" || x.mode === "subagent" || x.mode === "all" ? x.mode : "all") as WorkAgentInfo["mode"],
        native: typeof x.native === "boolean" ? x.native : undefined,
        hidden: typeof x.hidden === "boolean" ? x.hidden : undefined,
        color: typeof x.color === "string" ? x.color : undefined,
        model:
          x.model && typeof x.model === "object"
            ? {
                providerID: String((x.model as Record<string, unknown>).providerID ?? ""),
                modelID: String((x.model as Record<string, unknown>).modelID ?? ""),
              }
            : null,
        variant: typeof x.variant === "string" ? x.variant : null,
      }))
      .filter((a) => a.name && !a.hidden);
  }

  async listCommands(directory?: string | null): Promise<WorkCommandInfo[]> {
    const data = await this.request<unknown>("GET", "/command", { directory, timeoutMs: 15_000 });
    const list = Array.isArray(data) ? data : [];
    return list
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        name: String(x.name ?? ""),
        description: typeof x.description === "string" ? x.description : undefined,
        agent: typeof x.agent === "string" ? x.agent : undefined,
        model: typeof x.model === "string" ? x.model : undefined,
        source: (x.source === "command" || x.source === "mcp" || x.source === "skill"
          ? x.source
          : "command") as WorkCommandInfo["source"],
        template: typeof x.template === "string" ? x.template : undefined,
        hints: Array.isArray(x.hints) ? x.hints.map(String) : undefined,
      }))
      .filter((c) => c.name);
  }

  async getMcpStatus(directory?: string | null): Promise<Record<string, { status: string; error?: string }>> {
    const data = await this.request<unknown>("GET", "/mcp", { directory, timeoutMs: 15_000 });
    return data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, { status: string; error?: string }>)
      : {};
  }

  async connectMcp(name: string, directory?: string | null): Promise<void> {
    await this.request("POST", `/mcp/${encodeURIComponent(name)}/connect`, { directory, timeoutMs: 20_000 });
  }

  async disconnectMcp(name: string, directory?: string | null): Promise<void> {
    await this.request("POST", `/mcp/${encodeURIComponent(name)}/disconnect`, { directory, timeoutMs: 20_000 });
  }

  async getLspStatus(directory?: string | null): Promise<WorkLspStatus[]> {
    const data = await this.request<unknown>("GET", "/lsp", { directory, timeoutMs: 15_000 });
    const list = Array.isArray(data) ? data : [];
    return list
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        id: String(x.id ?? ""),
        name: String(x.name ?? x.id ?? ""),
        root: String(x.root ?? ""),
        status: (x.status === "error" ? "error" : "connected") as WorkLspStatus["status"],
      }))
      .filter((x) => x.id);
  }

  async getVcsInfo(directory?: string | null): Promise<{ branch: string | null }> {
    const data = await this.request<Record<string, unknown>>("GET", "/vcs", { directory, timeoutMs: 10_000 });
    return { branch: typeof data?.branch === "string" && data.branch.trim() ? data.branch.trim() : null };
  }

  async listPermissions(directory?: string | null): Promise<Array<Record<string, unknown>>> {
    const data = await this.request<unknown>("GET", "/permission", { directory, timeoutMs: 8_000 });
    return Array.isArray(data) ? (data as Array<Record<string, unknown>>) : [];
  }

  async listQuestions(directory?: string | null): Promise<Array<Record<string, unknown>>> {
    const data = await this.request<unknown>("GET", "/question", { directory, timeoutMs: 8_000 });
    return Array.isArray(data) ? (data as Array<Record<string, unknown>>) : [];
  }

  async getSessionStatuses(directory?: string | null): Promise<Record<string, { type?: string; message?: string }>> {
    const data = await this.request<unknown>("GET", "/session/status", { directory, timeoutMs: 8_000 });
    return data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, { type?: string; message?: string }>)
      : {};
  }

  async getSessionChildren(sessionId: string, directory?: string | null): Promise<string[]> {
    const data = await this.request<unknown>("GET", `/session/${encodeURIComponent(sessionId)}/children`, {
      directory,
      timeoutMs: 8_000,
    });
    if (!Array.isArray(data)) return [];
    return data
      .map((x) => (x && typeof x === "object" ? String((x as Record<string, unknown>).id ?? "") : ""))
      .filter(Boolean);
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

  async *streamEvents(
    directory: string | null,
    signal: AbortSignal,
    onOpen?: () => void,
  ): AsyncGenerator<OpenCodeEvent> {
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
    onOpen?.();
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
