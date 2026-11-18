import fs from "node:fs";
import path from "node:path";
import { IPC } from "../../shared/ipc-contract";
import { loadConfig } from "../config";
import { handle } from "./common";
import { scoped } from "../logger";
import {
  listConversations,
  createConversation,
  getConversation,
  renameConversation,
  deleteConversation,
} from "../work/repository";
import { approveRun, clarifyRun, sendMessage, stopRun } from "../work/runner";
import {
  clearProviderKey,
  getProviderKey,
  getWorkSettings,
  resolvedBaseUrl,
  saveWorkSettings,
} from "../work/settings";
import { ensureBuiltinKey } from "../runtime/config";

const logger = scoped("ipc:work");

interface TestResult {
  ok: boolean;
  latency_ms: number | null;
  model: string | null;
  detail: string | null;
}

async function testModel(): Promise<TestResult> {
  const settings = getWorkSettings();
  const model = settings.model;
  const started = Date.now();
  try {
    if (model.protocol === "builtin") {
      const key = (await ensureBuiltinKey()).trim();
      const resp = await fetch(`${resolvedBaseUrl(loadConfig().apiBase)}/models`, {
        headers: { Authorization: `Bearer ${key}` },
        signal: AbortSignal.timeout(15_000),
      });
      const text = await resp.text();
      if (!resp.ok) return { ok: false, latency_ms: null, model: null, detail: text.slice(0, 200) };
      return { ok: true, latency_ms: Date.now() - started, model: model.model || "whitz-default", detail: null };
    }

    const key = getProviderKey(model.protocol);
    if (!key) return { ok: false, latency_ms: null, model: null, detail: "尚未填写 API Key" };
    const base = model.base_url.replace(/\/+$/, "");
    if (model.protocol === "anthropic") {
      const resp = await fetch(`${base}/v1/messages`, {
        method: "POST",
        headers: {
          "x-api-key": key,
          "anthropic-version": "2023-06-01",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: model.model,
          max_tokens: 8,
          messages: [{ role: "user", content: "ping" }],
        }),
        signal: AbortSignal.timeout(20_000),
      });
      return finish(resp, started, model.model);
    }
    if (model.protocol === "google") {
      const resp = await fetch(
        `${base}/v1beta/models/${encodeURIComponent(model.model)}:generateContent?key=${encodeURIComponent(key)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ contents: [{ parts: [{ text: "ping" }] }], generationConfig: { maxOutputTokens: 8 } }),
          signal: AbortSignal.timeout(20_000),
        },
      );
      return finish(resp, started, model.model);
    }
    const resp = await fetch(`${base}/chat/completions`, {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model.model,
        max_tokens: 8,
        messages: [{ role: "user", content: "ping" }],
      }),
      signal: AbortSignal.timeout(20_000),
    });
    return finish(resp, started, model.model);
  } catch (err) {
    return {
      ok: false,
      latency_ms: null,
      model: null,
      detail: err instanceof Error ? err.message : "连接失败",
    };
  }
}

async function finish(resp: Response, started: number, model: string): Promise<TestResult> {
  const text = await resp.text();
  if (!resp.ok) {
    return { ok: false, latency_ms: null, model: null, detail: text.slice(0, 240) };
  }
  return { ok: true, latency_ms: Date.now() - started, model, detail: null };
}

function exportConversation(id: string): { path: string } {
  const detail = getConversation(id);
  if (!detail) throw new Error("对话不存在");
  const lines = [`# ${detail.conversation.title}`, "", `> 导出时间：${new Date().toLocaleString()}`, ""];
  for (const message of detail.messages) {
    if (message.role === "tool") {
      lines.push(`- 工具 ${message.tool_name ?? ""} (${message.status})`, "");
      continue;
    }
    lines.push(message.role === "user" ? "## 用户" : "## Whitz Work", "", message.content, "");
  }
  const targetDir = path.join(process.env.USERPROFILE ?? process.cwd(), "Documents", "Whitz Work");
  fs.mkdirSync(targetDir, { recursive: true });
  const file = path.join(targetDir, `${detail.conversation.title.replace(/[\\/:*?"<>|]/g, "_")}.md`);
  fs.writeFileSync(file, lines.join("\n"), "utf-8");
  return { path: file };
}

export function registerWorkHandlers(): void {
  handle(IPC.workList, () => listConversations());
  handle(IPC.workCreate, (title?: string) => createConversation(title));
  handle(IPC.workGet, (id: string) => {
    const detail = getConversation(id);
    if (!detail) throw new Error("对话不存在");
    return detail;
  });
  handle(IPC.workRename, (id: string, title: string) => renameConversation(id, title));
  handle(IPC.workDelete, (id: string) => deleteConversation(id));
  handle(IPC.workSend, (conversationId: string, content: string) => sendMessage(conversationId, content));
  handle(IPC.workStop, (conversationId: string) => stopRun(conversationId));
  handle(IPC.workApprove, (conversationId: string, requestId: string, generation: number, choice: "once" | "always" | "deny") =>
    approveRun(conversationId, requestId, generation, choice),
  );
  handle(IPC.workClarify, (conversationId: string, requestId: string, generation: number, answer: string) =>
    clarifyRun(conversationId, requestId, generation, answer),
  );
  handle(IPC.workSettingsGet, () => getWorkSettings());
  handle(IPC.workSettingsSave, (patch: Record<string, unknown>) => saveWorkSettings(patch));
  handle(IPC.workSettingsClearKey, () => clearProviderKey());
  handle(IPC.workTestModel, () => testModel());
  handle(IPC.workExport, (id: string) => exportConversation(id));
  logger.info("work ipc registered");
}
