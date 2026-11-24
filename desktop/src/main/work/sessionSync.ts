import fs from "node:fs";
import path from "node:path";
import type {
  WorkConversation,
  WorkConversationSummary,
  WorkRemoteSessionSummary,
  WorkTimelineItem,
  WorkTokenUsage,
} from "../../shared/work-types";
import { getStatus, startRuntime } from "../runtime/opencodeRuntime";
import { OpenCodeClient, type OpenCodeMessageWithParts } from "./opencodeClient";
import {
  addMessage,
  createConversation,
  getActiveWorkspacePath,
  getConversation,
  getConversationByOpenCodeSession,
  getConversationMeta,
  updateConversationMeta,
} from "./repository";

async function ensureReady(): Promise<void> {
  const status = getStatus();
  if (status.running) return;
  if (!status.installed) throw new Error("未检测到本机 OpenCode CLI");
  await startRuntime();
}

function toIso(epochMs?: number): string {
  if (typeof epochMs === "number" && Number.isFinite(epochMs) && epochMs > 0) {
    return new Date(epochMs).toISOString();
  }
  return new Date().toISOString();
}

export function convertOpenCodePartsToTimeline(parts: Array<Record<string, unknown>>): {
  text: string;
  timeline: WorkTimelineItem[];
} {
  const timeline: WorkTimelineItem[] = [];
  let text = "";
  let textSegmentsSinceLastTool = "";

  const flushCommentary = () => {
    const trimmed = textSegmentsSinceLastTool.trim();
    if (trimmed) {
      timeline.push({
        id: `comment:${timeline.length}`,
        kind: "commentary",
        text: trimmed,
        status: "completed",
      });
      textSegmentsSinceLastTool = "";
    }
  };

  for (const part of parts) {
    const type = String(part.type ?? "");
    const id = String(part.id ?? `part_${timeline.length}`);
    if (type === "reasoning") {
      const content = String(part.text ?? "");
      if (content.trim()) {
        timeline.push({
          id: `think:${id}`,
          kind: "thinking",
          title: "深度思考",
          text: content,
          status: "completed",
        });
      }
      continue;
    }
    if (type === "text" && !part.synthetic && !part.ignored) {
      const chunk = String(part.text ?? "");
      if (chunk) {
        textSegmentsSinceLastTool = textSegmentsSinceLastTool ? `${textSegmentsSinceLastTool}\n\n${chunk}` : chunk;
        text = textSegmentsSinceLastTool;
      }
      continue;
    }
    if (type === "tool") {
      flushCommentary();
      const toolName = String(part.tool ?? "tool");
      const callId = String(part.callID ?? id);
      const stateObj = (part.state as Record<string, unknown> | undefined) ?? {};
      const statusRaw = String(stateObj.status ?? "completed");
      const timeObj = stateObj.time as Record<string, number> | undefined;
      const duration =
        timeObj && typeof timeObj.end === "number" && typeof timeObj.start === "number"
          ? Math.max(0, (timeObj.end - timeObj.start) / 1000)
          : null;
      const meta = (stateObj.metadata as Record<string, unknown> | undefined) ?? {};
      const childSessionId = typeof meta.sessionId === "string"
        ? meta.sessionId
        : typeof meta.sessionID === "string"
          ? meta.sessionID
          : null;
      timeline.push({
        id: callId,
        kind: toolName === "task" && childSessionId ? "subagent" : "tool",
        tool: toolName,
        call_id: callId,
        title: stateObj.title ? String(stateObj.title) : null,
        args: stateObj.input ?? null,
        result: stateObj.output ?? stateObj.title ?? null,
        error: statusRaw === "error" ? String(stateObj.error ?? "工具执行失败") : null,
        duration,
        status: statusRaw === "error" ? "failed" : statusRaw === "running" || statusRaw === "pending" ? "running" : "completed",
        child_session_id: childSessionId,
      });
      continue;
    }
    if (type === "subtask") {
      flushCommentary();
      timeline.push({
        id: `subtask:${id}`,
        kind: "subagent",
        tool: "task",
        title: String(part.description ?? part.agent ?? "子任务"),
        text: String(part.prompt ?? ""),
        status: "completed",
      });
      continue;
    }
    if (type === "patch") {
      const files = Array.isArray(part.files) ? part.files.map(String).filter(Boolean) : [];
      if (files.length) {
        timeline.push({
          id: `patch:${id}`,
          kind: "patch",
          title: `快照改动 ${files.length} 个文件`,
          files,
          status: "completed",
        });
      }
      continue;
    }
    if (type === "compaction") {
      timeline.push({
        id: `compact:${id}`,
        kind: "compaction",
        title: part.auto ? "自动压缩上下文" : "压缩上下文",
        status: "completed",
      });
      continue;
    }
    if (type === "retry") {
      timeline.push({
        id: `retry:${id}`,
        kind: "retry",
        title: `第 ${Number(part.attempt ?? 1)} 次重试`,
        attempt: Number(part.attempt ?? 1),
        status: "completed",
      });
    }
  }

  return { text: textSegmentsSinceLastTool || text, timeline };
}

function extractUsageFromInfo(info: Record<string, unknown>): WorkTokenUsage | null {
  const tokens = info.tokens as Record<string, unknown> | undefined;
  if (!tokens || typeof tokens !== "object") return null;
  const input = Number(tokens.input ?? 0) || 0;
  const output = Number(tokens.output ?? 0) || 0;
  const reasoning = Number(tokens.reasoning ?? 0) || 0;
  const cache = (tokens.cache as Record<string, unknown> | undefined) ?? {};
  const cacheRead = Number(cache.read ?? 0) || 0;
  const cacheWrite = Number(cache.write ?? 0) || 0;
  const cost = Number(info.cost ?? 0) || 0;
  const total = input + output + reasoning + cacheRead + cacheWrite;
  if (!total) return null;
  return {
    input,
    output,
    reasoning,
    cache_read: cacheRead,
    cache_write: cacheWrite,
    cost,
    total,
    context_limit: null,
  };
}

export async function listRemoteSessions(workspacePath?: string | null): Promise<WorkRemoteSessionSummary[]> {
  if (!getStatus().running) return [];
  const dir = workspacePath ?? getActiveWorkspacePath();
  const client = new OpenCodeClient();
  const list = await client.listSessions(dir);
  const out: WorkRemoteSessionSummary[] = [];
  for (const s of list) {
    if (!s?.id || s.parentID) continue; // skip internal child/subagent sessions
    const linked = getConversationByOpenCodeSession(s.id);
    const summary: WorkConversationSummary | null = s.summary
      ? {
          additions: Number(s.summary.additions ?? 0) || 0,
          deletions: Number(s.summary.deletions ?? 0) || 0,
          files: Number(s.summary.files ?? 0) || 0,
        }
      : null;
    out.push({
      id: s.id,
      title: s.title || "OpenCode 会话",
      directory: s.directory || dir || "",
      parent_id: s.parentID ?? null,
      created_at: toIso(s.time?.created),
      updated_at: toIso(s.time?.updated),
      share_url: s.share?.url ?? null,
      summary,
      cost: typeof s.cost === "number" ? s.cost : 0,
      linked_conversation_id: linked?.id ?? null,
    });
  }
  return out.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export async function importRemoteSession(sessionId: string, workspacePath?: string | null): Promise<WorkConversation> {
  await ensureReady();
  const existing = getConversationByOpenCodeSession(sessionId);
  if (existing) return existing;

  const dir = workspacePath ?? getActiveWorkspacePath();
  const client = new OpenCodeClient();
  const [session, msgList] = await Promise.all([
    client.getSession(sessionId, dir),
    client.getSessionMessages(sessionId, dir),
  ]);
  const targetDir = session?.directory || dir || null;
  const summary: WorkConversationSummary | null = session?.summary
    ? {
        additions: Number(session.summary.additions ?? 0) || 0,
        deletions: Number(session.summary.deletions ?? 0) || 0,
        files: Number(session.summary.files ?? 0) || 0,
      }
    : null;

  const conv = createConversation(session?.title || "导入的 OpenCode 会话", targetDir, {
    opencode_session_id: sessionId,
    share_url: session?.share?.url ?? null,
    summary,
    total_cost: typeof session?.cost === "number" ? session.cost : 0,
  });

  for (const entry of msgList as OpenCodeMessageWithParts[]) {
    const info = entry?.info ?? {};
    const parts = Array.isArray(entry?.parts) ? entry.parts : [];
    const role = info.role === "user" ? "user" : info.role === "assistant" ? "assistant" : null;
    if (!role) continue;
    const ocMsgId = typeof info.id === "string" ? info.id : undefined;

    if (role === "user") {
      const userText = parts
        .filter((p) => p.type === "text" && !p.synthetic && !p.ignored)
        .map((p) => String(p.text ?? ""))
        .join("\n")
        .trim();
      const attachments = parts
        .filter((p) => p.type === "file")
        .map((p, idx) => ({
          id: String(p.id ?? `att_${idx}`),
          name: String(p.filename ?? "文件"),
          path: String(p.url ?? ""),
          kind: String(p.mime ?? "").startsWith("image/") ? "image" : "file",
          size: 0,
        }));
      addMessage({
        conversation_id: conv.id,
        role: "user",
        content: userText || "(附件消息)",
        status: "completed",
        tool_payload: {
          ...(ocMsgId ? { opencode_message_id: ocMsgId } : {}),
          ...(attachments.length ? { attachments } : {}),
        },
      });
    } else {
      const { text, timeline } = convertOpenCodePartsToTimeline(parts);
      const usage = extractUsageFromInfo(info);
      addMessage({
        conversation_id: conv.id,
        role: "assistant",
        content: text,
        status: info.error ? "failed" : "completed",
        tool_payload: {
          ...(ocMsgId ? { opencode_message_id: ocMsgId } : {}),
          timeline,
          ...(usage ? { usage } : {}),
        },
      });
    }
  }

  return conv;
}

export async function getSubsessionTimeline(
  childSessionId: string,
  workspacePath?: string | null,
): Promise<WorkTimelineItem[]> {
  if (!getStatus().running || !childSessionId) return [];
  const dir = workspacePath ?? getActiveWorkspacePath();
  const messages = await new OpenCodeClient().getSessionMessages(childSessionId, dir);
  const all: WorkTimelineItem[] = [];
  for (const m of messages) {
    if (m.info?.role !== "assistant") continue;
    const { text, timeline } = convertOpenCodePartsToTimeline(Array.isArray(m.parts) ? m.parts : []);
    all.push(...timeline);
    if (text.trim()) {
      all.push({
        id: `sub-final:${String(m.info?.id ?? all.length)}`,
        kind: "commentary",
        text: text.trim(),
        status: "completed",
      });
    }
  }
  return all;
}

export async function shareConversation(conversationId: string): Promise<{ url: string }> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  if (!conv.opencode_session_id) throw new Error("当前会话尚未发送消息，暂无法生成分享链接");
  await ensureReady();
  const dir = conv.workspace_path || getActiveWorkspacePath();
  const res = await new OpenCodeClient().shareSession(conv.opencode_session_id, dir);
  updateConversationMeta(conversationId, { share_url: res.url });
  return res;
}

export async function unshareConversation(conversationId: string): Promise<void> {
  const conv = getConversationMeta(conversationId);
  if (!conv) throw new Error("对话不存在");
  if (conv.opencode_session_id && getStatus().running) {
    const dir = conv.workspace_path || getActiveWorkspacePath();
    await new OpenCodeClient().unshareSession(conv.opencode_session_id, dir);
  }
  updateConversationMeta(conversationId, { share_url: null });
}

export async function syncRenameToOpenCode(conversationId: string, title: string): Promise<void> {
  const conv = getConversationMeta(conversationId);
  if (!conv?.opencode_session_id || !getStatus().running) return;
  const dir = conv.workspace_path || getActiveWorkspacePath();
  await new OpenCodeClient().updateSession(conv.opencode_session_id, { title }, dir).catch(() => undefined);
}

export async function syncDeleteToOpenCode(conversationId: string): Promise<void> {
  const conv = getConversationMeta(conversationId);
  if (!conv?.opencode_session_id || !getStatus().running) return;
  const dir = conv.workspace_path || getActiveWorkspacePath();
  await new OpenCodeClient().deleteSession(conv.opencode_session_id, dir).catch(() => undefined);
}

export async function exportConversationJson(conversationId: string): Promise<{ path: string }> {
  const detail = getConversation(conversationId);
  if (!detail) throw new Error("对话不存在");
  let remoteMessages: OpenCodeMessageWithParts[] | null = null;
  if (detail.conversation.opencode_session_id && getStatus().running) {
    const dir = detail.conversation.workspace_path || getActiveWorkspacePath();
    remoteMessages = await new OpenCodeClient()
      .getSessionMessages(detail.conversation.opencode_session_id, dir)
      .catch(() => null);
  }
  const targetDir = path.join(process.env.USERPROFILE ?? process.cwd(), "Documents", "Whitz Work");
  fs.mkdirSync(targetDir, { recursive: true });
  const safeName = detail.conversation.title.replace(/[\\/:*?"<>|]/g, "_");
  const file = path.join(targetDir, `${safeName}.opencode.json`);
  fs.writeFileSync(
    file,
    JSON.stringify(
      {
        exported_at: new Date().toISOString(),
        conversation: detail.conversation,
        messages: detail.messages,
        ...(remoteMessages ? { opencode_messages: remoteMessages } : {}),
      },
      null,
      2,
    ),
    "utf-8",
  );
  return { path: file };
}
