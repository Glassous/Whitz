import { opencodeAuthHeader, opencodeBaseUrl } from "../runtime/opencodeRuntime";
import type { LiveProviderPayload } from "../runtime/opencodeConfig";
import type {
  WorkAgentInfo,
  WorkCommandInfo,
  WorkFindMatch,
  WorkFormatterStatus,
  WorkGlobalEvent,
  WorkLspStatus,
  WorkProviderAuthMethod,
  WorkProviderOAuthStart,
  WorkPtyInfo,
  WorkSessionDiffItem,
  WorkShellOption,
  WorkSkillItem,
  WorkSymbolMatch,
  WorkWorktreeInfo,
} from "../../shared/work-types";

export type PromptPartInput =
  | { type: "text"; text: string }
  | { type: "file"; mime: string; filename?: string; url: string }
  | { type: "agent"; name: string };

export interface OpenCodeEvent {
  type: string;
  properties: Record<string, unknown>;
}

export interface OpenCodeSessionRecord {
  id: string;
  title: string;
  directory: string;
  parentID?: string;
  share?: { url?: string };
  cost?: number;
  summary?: { additions?: number; deletions?: number; files?: number };
  time?: { created?: number; updated?: number };
}

export interface OpenCodeMessageWithParts {
  info: Record<string, unknown>;
  parts: Array<Record<string, unknown>>;
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

  // ---- Sessions ----

  async listSessions(directory?: string | null): Promise<OpenCodeSessionRecord[]> {
    const data = await this.request<unknown>("GET", "/session", { directory, timeoutMs: 15_000 });
    return Array.isArray(data) ? (data as OpenCodeSessionRecord[]) : [];
  }

  async getSession(sessionId: string, directory?: string | null): Promise<OpenCodeSessionRecord | null> {
    return this.request<OpenCodeSessionRecord>("GET", `/session/${encodeURIComponent(sessionId)}`, {
      directory,
      timeoutMs: 12_000,
    });
  }

  async createSession(title: string, directory?: string | null): Promise<string> {
    const data = await this.request<Record<string, unknown>>("POST", "/session", {
      directory,
      body: { title: title || "新的工作区对话" },
    });
    return String(data.id ?? "");
  }

  async updateSession(sessionId: string, patch: { title?: string }, directory?: string | null): Promise<void> {
    await this.request("PATCH", `/session/${encodeURIComponent(sessionId)}`, {
      directory,
      body: patch,
      timeoutMs: 12_000,
    });
  }

  async deleteSession(sessionId: string, directory?: string | null): Promise<void> {
    await this.request("DELETE", `/session/${encodeURIComponent(sessionId)}`, {
      directory,
      timeoutMs: 12_000,
    });
  }

  async getSessionMessages(sessionId: string, directory?: string | null): Promise<OpenCodeMessageWithParts[]> {
    const data = await this.request<unknown>("GET", `/session/${encodeURIComponent(sessionId)}/message`, {
      directory,
      timeoutMs: 25_000,
    });
    return Array.isArray(data) ? (data as OpenCodeMessageWithParts[]) : [];
  }

  async shareSession(sessionId: string, directory?: string | null): Promise<{ url: string }> {
    const data = await this.request<Record<string, unknown>>("POST", `/session/${encodeURIComponent(sessionId)}/share`, {
      directory,
      timeoutMs: 20_000,
    });
    const share = (data?.share as Record<string, unknown> | undefined) ?? data;
    const url = typeof share?.url === "string" ? share.url : "";
    if (!url) throw new Error("OpenCode 未返回分享链接");
    return { url };
  }

  async unshareSession(sessionId: string, directory?: string | null): Promise<void> {
    await this.request("DELETE", `/session/${encodeURIComponent(sessionId)}/share`, {
      directory,
      timeoutMs: 15_000,
    });
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
        file: String(x.file ?? x.path ?? ""),
        patch: typeof x.patch === "string" ? x.patch : undefined,
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

  // ---- Agents, Commands, Skills ----

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

  // ---- Search (Find Files / Text / Symbols) ----

  async findFiles(query: string, directory?: string | null): Promise<string[]> {
    const data = await this.request<unknown>("GET", `/find/file?query=${encodeURIComponent(query)}`, {
      directory,
      timeoutMs: 10_000,
    });
    if (!Array.isArray(data)) return [];
    return data.map((x) => String(x ?? "")).filter(Boolean);
  }

  async findText(pattern: string, directory?: string | null): Promise<WorkFindMatch[]> {
    const data = await this.request<unknown>("GET", `/find?pattern=${encodeURIComponent(pattern)}`, {
      directory,
      timeoutMs: 15_000,
    });
    if (!Array.isArray(data)) return [];
    const out: WorkFindMatch[] = [];
    for (const raw of data.slice(0, 120)) {
      if (!raw || typeof raw !== "object") continue;
      const obj = raw as Record<string, unknown>;
      const pathObj = obj.path as Record<string, unknown> | string | undefined;
      const linesObj = obj.lines as Record<string, unknown> | string | undefined;
      const filePath = typeof pathObj === "string" ? pathObj : String(pathObj?.text ?? "");
      const lineText = typeof linesObj === "string" ? linesObj : String(linesObj?.text ?? "");
      const lineNum = Number(obj.line_number ?? 1) || 1;
      if (!filePath) continue;
      const submatches = Array.isArray(obj.submatches)
        ? (obj.submatches as Array<Record<string, unknown>>).map((sm) => {
            const m = sm.match as Record<string, unknown> | string | undefined;
            return {
              match: typeof m === "string" ? m : String(m?.text ?? ""),
              start: Number(sm.start ?? 0) || 0,
              end: Number(sm.end ?? 0) || 0,
            };
          })
        : undefined;
      out.push({ path: filePath, line_number: lineNum, lines: lineText.trimEnd(), submatches });
    }
    return out;
  }

  async findSymbols(query: string, directory?: string | null): Promise<WorkSymbolMatch[]> {
    const data = await this.request<unknown>("GET", `/find/symbol?query=${encodeURIComponent(query)}`, {
      directory,
      timeoutMs: 12_000,
    });
    if (!Array.isArray(data)) return [];
    const out: WorkSymbolMatch[] = [];
    for (const raw of data.slice(0, 80)) {
      if (!raw || typeof raw !== "object") continue;
      const obj = raw as Record<string, unknown>;
      const loc = (obj.location as Record<string, unknown> | undefined) ?? {};
      const uri = String(loc.uri ?? "");
      const range = (loc.range as Record<string, unknown> | undefined) ?? {};
      const start = (range.start as Record<string, unknown> | undefined) ?? {};
      const name = String(obj.name ?? "");
      if (!name) continue;
      let rel = uri.replace(/^file:\/+/i, "");
      if (directory) {
        const normDir = directory.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
        const normRel = rel.replace(/\\/g, "/");
        if (normRel.toLowerCase().startsWith(normDir + "/")) {
          rel = normRel.slice(normDir.length + 1);
        }
      }
      out.push({
        name,
        kind: Number(obj.kind ?? 0) || 0,
        path: decodeURIComponent(rel),
        line: (Number(start.line ?? 0) || 0) + 1,
      });
    }
    return out;
  }

  // ---- MCP, LSP, Formatter, VCS ----

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

  async authenticateMcp(name: string, directory?: string | null): Promise<void> {
    await this.request("POST", `/mcp/${encodeURIComponent(name)}/auth/authenticate`, {
      directory,
      timeoutMs: 120_000,
    });
  }

  async removeMcpAuth(name: string, directory?: string | null): Promise<void> {
    await this.request("DELETE", `/mcp/${encodeURIComponent(name)}/auth`, { directory, timeoutMs: 15_000 });
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

  async getFormatterStatus(directory?: string | null): Promise<WorkFormatterStatus[]> {
    const data = await this.request<unknown>("GET", "/formatter", { directory, timeoutMs: 15_000 });
    const list = Array.isArray(data) ? data : [];
    return list
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        name: String(x.name ?? ""),
        extensions: Array.isArray(x.extensions) ? x.extensions.map(String) : [],
        enabled: Boolean(x.enabled),
      }))
      .filter((x) => x.name);
  }

  async getVcsInfo(directory?: string | null): Promise<{ branch: string | null }> {
    const data = await this.request<Record<string, unknown>>("GET", "/vcs", { directory, timeoutMs: 10_000 });
    return { branch: typeof data?.branch === "string" && data.branch.trim() ? data.branch.trim() : null };
  }

  // ---- PTY ----

  async listShells(directory?: string | null): Promise<WorkShellOption[]> {
    const data = await this.request<unknown>("GET", "/pty/shells", { directory, timeoutMs: 10_000 });
    const list = Array.isArray(data) ? data : [];
    return list
      .filter((x): x is Record<string, unknown> => Boolean(x && typeof x === "object"))
      .map((x) => ({
        name: String(x.name ?? x.label ?? x.path ?? "Shell"),
        path: String(x.path ?? x.command ?? ""),
        args: Array.isArray(x.args) ? x.args.map(String) : undefined,
        is_default: Boolean(x.default ?? x.isDefault),
      }))
      .filter((s) => s.path);
  }

  async listPtys(directory?: string | null): Promise<WorkPtyInfo[]> {
    const data = await this.request<unknown>("GET", "/pty", { directory, timeoutMs: 10_000 });
    return Array.isArray(data) ? (data as WorkPtyInfo[]) : [];
  }

  async createPty(
    payload: { command?: string; args?: string[]; cwd?: string; title?: string; env?: Record<string, string> },
    directory?: string | null,
  ): Promise<WorkPtyInfo> {
    return this.request<WorkPtyInfo>("POST", "/pty", { directory, body: payload, timeoutMs: 15_000 });
  }

  async updatePty(
    ptyId: string,
    patch: { title?: string; size?: { rows: number; cols: number } },
    directory?: string | null,
  ): Promise<WorkPtyInfo> {
    return this.request<WorkPtyInfo>("PUT", `/pty/${encodeURIComponent(ptyId)}`, {
      directory,
      body: patch,
      timeoutMs: 10_000,
    });
  }

  async removePty(ptyId: string, directory?: string | null): Promise<void> {
    await this.request("DELETE", `/pty/${encodeURIComponent(ptyId)}`, { directory, timeoutMs: 10_000 });
  }

  async createPtyConnectToken(ptyId: string, directory?: string | null): Promise<string> {
    const data = await this.request<Record<string, unknown>>(
      "POST",
      `/pty/${encodeURIComponent(ptyId)}/connect-token`,
      { directory, timeoutMs: 10_000 },
    );
    const ticket = typeof data?.ticket === "string" ? data.ticket : typeof data?.token === "string" ? data.token : "";
    if (!ticket) throw new Error("未能获取终端连接票据");
    return ticket;
  }

  // ---- Worktrees ----

  async listWorktrees(directory?: string | null): Promise<string[]> {
    const data = await this.request<unknown>("GET", "/experimental/worktree", { directory, timeoutMs: 15_000 });
    return Array.isArray(data) ? data.map(String).filter(Boolean) : [];
  }

  async createWorktree(name?: string, directory?: string | null): Promise<WorkWorktreeInfo> {
    return this.request<WorkWorktreeInfo>("POST", "/experimental/worktree", {
      directory,
      body: name?.trim() ? { name: name.trim() } : {},
      timeoutMs: 30_000,
    });
  }

  async removeWorktree(targetDir: string, directory?: string | null): Promise<void> {
    await this.request("DELETE", "/experimental/worktree", {
      directory,
      body: { directory: targetDir },
      timeoutMs: 20_000,
    });
  }

  async resetWorktree(targetDir: string, directory?: string | null): Promise<void> {
    await this.request("POST", "/experimental/worktree/reset", {
      directory,
      body: { directory: targetDir },
      timeoutMs: 20_000,
    });
  }

  // ---- Permissions, Questions, Session Status ----

  async listPermissions(directory?: string | null): Promise<Array<Record<string, unknown>>> {
    const data = await this.request<unknown>("GET", "/permission", { directory, timeoutMs: 8_000 });
    return Array.isArray(data) ? (data as Array<Record<string, unknown>>) : [];
  }

  async listQuestions(directory?: string | null): Promise<Array<Record<string, unknown>>> {
    const data = await this.request<unknown>("GET", "/question", { directory, timeoutMs: 8_000 });
    return Array.isArray(data) ? (data as Array<Record<string, unknown>>) : [];
  }

  async getSessionStatuses(
    directory?: string | null,
  ): Promise<Record<string, { type?: string; message?: string; attempt?: number; next?: number }>> {
    const data = await this.request<unknown>("GET", "/session/status", { directory, timeoutMs: 8_000 });
    return data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, { type?: string; message?: string; attempt?: number; next?: number }>)
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
      body: message?.trim() ? { reply, message: message.trim() } : { reply },
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

  // ---- Providers & OAuth & Upgrade ----

  async listProviders(directory?: string | null): Promise<LiveProviderPayload> {
    return this.request<LiveProviderPayload>("GET", "/provider", { directory, timeoutMs: 15_000 });
  }

  async listProviderAuthMethods(directory?: string | null): Promise<Record<string, WorkProviderAuthMethod[]>> {
    const data = await this.request<unknown>("GET", "/provider/auth", { directory, timeoutMs: 15_000 });
    return data && typeof data === "object" && !Array.isArray(data)
      ? (data as Record<string, WorkProviderAuthMethod[]>)
      : {};
  }

  async authorizeProviderOAuth(
    providerId: string,
    method: number,
    inputs?: Record<string, string>,
    directory?: string | null,
  ): Promise<WorkProviderOAuthStart> {
    return this.request<WorkProviderOAuthStart>(
      "POST",
      `/provider/${encodeURIComponent(providerId)}/oauth/authorize`,
      {
        directory,
        body: inputs && Object.keys(inputs).length ? { method, inputs } : { method },
        timeoutMs: 30_000,
      },
    );
  }

  async callbackProviderOAuth(
    providerId: string,
    method: number,
    code?: string,
    directory?: string | null,
  ): Promise<boolean> {
    const resp = await this.request<unknown>(
      "POST",
      `/provider/${encodeURIComponent(providerId)}/oauth/callback`,
      {
        directory,
        body: code?.trim() ? { method, code: code.trim() } : { method },
        timeoutMs: 120_000,
      },
    );
    return resp !== false;
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

  async upgradeGlobal(target?: string): Promise<unknown> {
    return this.request("POST", "/global/upgrade", {
      body: target?.trim() ? { target: target.trim() } : {},
      timeoutMs: 120_000,
    });
  }

  // ---- SSE Streams ----

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
    yield* readSseStream(resp.body, parseSseEvent);
  }

  async *streamGlobalEvents(signal: AbortSignal, onOpen?: () => void): AsyncGenerator<WorkGlobalEvent> {
    const url = `${this.base}/global/event`;
    const resp = await fetch(url, {
      headers: {
        ...opencodeAuthHeader(),
        Accept: "text/event-stream",
      },
      signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error(`OpenCode 全局事件流不可用（${resp.status}）`);
    }
    onOpen?.();
    yield* readSseStream(resp.body, parseGlobalSseEvent);
  }
}

async function* readSseStream<T>(
  body: ReadableStream<Uint8Array>,
  parser: (block: string) => T | null,
): AsyncGenerator<T> {
  const reader = body.getReader();
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
        const parsed = parser(block);
        if (parsed) yield parsed;
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSseData(block: string): Record<string, unknown> | null {
  const dataLines: string[] = [];
  for (const raw of block.split(/\r?\n/)) {
    if (!raw || raw.startsWith(":")) continue;
    if (raw.startsWith("data:")) dataLines.push(raw.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  try {
    const obj = JSON.parse(dataLines.join("\n"));
    return obj && typeof obj === "object" && !Array.isArray(obj) ? (obj as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function parseSseEvent(block: string): OpenCodeEvent | null {
  const obj = parseSseData(block);
  if (!obj) return null;
  const type = typeof obj.type === "string" ? obj.type : "";
  if (!type) return null;
  const properties =
    obj.properties && typeof obj.properties === "object" && !Array.isArray(obj.properties)
      ? (obj.properties as Record<string, unknown>)
      : {};
  return { type, properties };
}

function parseGlobalSseEvent(block: string): WorkGlobalEvent | null {
  const obj = parseSseData(block);
  if (!obj) return null;
  const directory = typeof obj.directory === "string" ? obj.directory : null;
  const payload =
    obj.payload && typeof obj.payload === "object" && !Array.isArray(obj.payload)
      ? (obj.payload as Record<string, unknown>)
      : obj;
  const type = typeof payload.type === "string" ? payload.type : "";
  if (!type) return null;
  const properties =
    payload.properties && typeof payload.properties === "object" && !Array.isArray(payload.properties)
      ? (payload.properties as Record<string, unknown>)
      : {};
  return { type, directory, properties };
}
