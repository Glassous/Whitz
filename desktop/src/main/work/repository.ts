import crypto from "node:crypto";
import path from "node:path";
import { getDb } from "./db";
import type {
  WorkConversation,
  WorkConversationDetail,
  WorkMessage,
  WorkRole,
  WorkWorkspace,
} from "../../shared/work-types";

const ACTIVE_WORKSPACE_KV = "active_workspace_path";

interface ConversationRow {
  id: string;
  title: string;
  opencode_session_id: string | null;
  workspace_path: string | null;
  is_pinned: number;
  model_ref: string | null;
  agent_name: string | null;
  variant: string | null;
  created_at: string;
  updated_at: string;
}

interface WorkspaceRow {
  id: string;
  path: string;
  name: string;
  last_opened_at: string;
  created_at: string;
}

interface MessageRow {
  id: string;
  conversation_id: string;
  role: WorkRole;
  content: string;
  status: WorkMessage["status"];
  tool_name: string | null;
  tool_payload: string | null;
  run_id: string | null;
  reverted: number;
  created_at: string;
}

function now(): string {
  return new Date().toISOString();
}

function toConversation(row: ConversationRow): WorkConversation {
  return {
    id: row.id,
    title: row.title,
    opencode_session_id: row.opencode_session_id ?? null,
    workspace_path: row.workspace_path ?? null,
    is_pinned: Boolean(row.is_pinned),
    model_ref: row.model_ref ?? null,
    agent_name: row.agent_name ?? null,
    variant: row.variant ?? null,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

function toMessage(row: MessageRow): WorkMessage {
  let payload: Record<string, unknown> | null = null;
  if (row.tool_payload) {
    try {
      payload = JSON.parse(row.tool_payload) as Record<string, unknown>;
    } catch {
      payload = null;
    }
  }
  return {
    id: row.id,
    conversation_id: row.conversation_id,
    role: row.role,
    content: row.content,
    status: row.status,
    tool_name: row.tool_name,
    tool_payload: payload,
    run_id: row.run_id ?? null,
    reverted: Boolean(row.reverted),
    created_at: row.created_at,
  };
}

export function listConversations(workspacePath?: string | null): WorkConversation[] {
  const rows =
    workspacePath !== undefined && workspacePath !== null && workspacePath !== ""
      ? (getDb()
          .prepare(
            `SELECT id, title, opencode_session_id, workspace_path, is_pinned, model_ref, agent_name, variant, created_at, updated_at
             FROM conversations WHERE archived = 0 AND workspace_path = ?
             ORDER BY is_pinned DESC, updated_at DESC`,
          )
          .all(path.resolve(workspacePath)) as ConversationRow[])
      : (getDb()
          .prepare(
            `SELECT id, title, opencode_session_id, workspace_path, is_pinned, model_ref, agent_name, variant, created_at, updated_at
             FROM conversations WHERE archived = 0
             ORDER BY is_pinned DESC, updated_at DESC`,
          )
          .all() as ConversationRow[]);
  return rows.map(toConversation);
}

export function createConversation(
  title = "新的工作区对话",
  workspacePath?: string | null,
  init?: {
    opencode_session_id?: string | null;
    model_ref?: string | null;
    agent_name?: string | null;
    variant?: string | null;
  },
): WorkConversation {
  const id = crypto.randomUUID();
  const stamp = now();
  const cleanTitle = title.trim() || "新的工作区对话";
  const resolvedWorkspace = workspacePath ? path.resolve(workspacePath) : getActiveWorkspacePath();
  const opencodeSessionId = init?.opencode_session_id ?? null;
  const modelRef = init?.model_ref ?? null;
  const agentName = init?.agent_name ?? null;
  const variant = init?.variant ?? null;
  getDb()
    .prepare(
      `INSERT INTO conversations (id, title, opencode_session_id, workspace_path, is_pinned, model_ref, agent_name, variant, created_at, updated_at, archived)
       VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, 0)`,
    )
    .run(id, cleanTitle, opencodeSessionId, resolvedWorkspace, modelRef, agentName, variant, stamp, stamp);
  return {
    id,
    title: cleanTitle,
    opencode_session_id: opencodeSessionId,
    workspace_path: resolvedWorkspace,
    is_pinned: false,
    model_ref: modelRef,
    agent_name: agentName,
    variant,
    created_at: stamp,
    updated_at: stamp,
  };
}

export function getConversationMeta(id: string): ConversationRow | null {
  const row = getDb()
    .prepare(
      `SELECT id, title, opencode_session_id, workspace_path, is_pinned, model_ref, agent_name, variant, created_at, updated_at
       FROM conversations WHERE id = ? AND archived = 0`,
    )
    .get(id) as ConversationRow | undefined;
  return row ?? null;
}

export function setConversationPrefs(
  id: string,
  prefs: { model_ref?: string | null; agent_name?: string | null; variant?: string | null },
): WorkConversation {
  const row = getConversationMeta(id);
  if (!row) throw new Error("对话不存在");
  const nextModel = prefs.model_ref !== undefined ? prefs.model_ref : row.model_ref;
  const nextAgent = prefs.agent_name !== undefined ? prefs.agent_name : row.agent_name;
  const nextVariant = prefs.variant !== undefined ? prefs.variant : row.variant;
  getDb()
    .prepare(`UPDATE conversations SET model_ref = ?, agent_name = ?, variant = ? WHERE id = ?`)
    .run(nextModel ?? null, nextAgent ?? null, nextVariant ?? null, id);
  return toConversation(getConversationMeta(id)!);
}

export function setOpenCodeSession(conversationId: string, sessionId: string): void {
  getDb()
    .prepare(`UPDATE conversations SET opencode_session_id = ?, updated_at = ? WHERE id = ?`)
    .run(sessionId, now(), conversationId);
}

export function touchConversation(conversationId: string): void {
  getDb().prepare(`UPDATE conversations SET updated_at = ? WHERE id = ?`).run(now(), conversationId);
}

export function renameConversation(id: string, title: string): void {
  getDb()
    .prepare(`UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?`)
    .run(title.trim() || "未命名对话", now(), id);
}

export function pinConversation(id: string, isPinned: boolean): void {
  getDb().prepare(`UPDATE conversations SET is_pinned = ? WHERE id = ?`).run(isPinned ? 1 : 0, id);
}

export function deleteConversation(id: string): void {
  getDb().prepare(`DELETE FROM conversations WHERE id = ?`).run(id);
}

export function getConversation(id: string): WorkConversationDetail | null {
  const row = getConversationMeta(id);
  if (!row) return null;
  const rows = getDb()
    .prepare(
      `SELECT id, conversation_id, role, content, status, tool_name, tool_payload, run_id, reverted, created_at
       FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC`,
    )
    .all(id) as MessageRow[];
  const allMessages = rows.map(toMessage);
  const activeMessages = allMessages.filter((m) => !m.reverted);
  const revertedCount = allMessages.length - activeMessages.length;
  const streaming = [...activeMessages]
    .reverse()
    .find((m) => m.role === "assistant" && (m.status === "streaming" || m.status === "waiting"));
  return {
    conversation: toConversation(row),
    messages: activeMessages,
    active_run_id: streaming?.run_id ?? null,
    active_run_status: streaming?.status ?? null,
    reverted_count: revertedCount,
  };
}

export function getMessageRow(id: string): WorkMessage | null {
  const row = getDb()
    .prepare(
      `SELECT id, conversation_id, role, content, status, tool_name, tool_payload, run_id, reverted, created_at
       FROM messages WHERE id = ?`,
    )
    .get(id) as MessageRow | undefined;
  return row ? toMessage(row) : null;
}

export function markMessagesRevertedFrom(conversationId: string, fromMessageId: string): void {
  const rows = getDb()
    .prepare(`SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC`)
    .all(conversationId) as Array<{ id: string }>;
  const idx = rows.findIndex((r) => r.id === fromMessageId);
  if (idx < 0) return;
  const targetIds = rows.slice(idx).map((r) => r.id);
  const stmt = getDb().prepare(`UPDATE messages SET reverted = 1 WHERE id = ?`);
  for (const mid of targetIds) stmt.run(mid);
}

export function unrevertAllMessages(conversationId: string): void {
  getDb().prepare(`UPDATE messages SET reverted = 0 WHERE conversation_id = ?`).run(conversationId);
}

export function copyMessagesUpTo(sourceConvId: string, targetConvId: string, upToMessageId?: string | null): void {
  const rows = getDb()
    .prepare(
      `SELECT id, conversation_id, role, content, status, tool_name, tool_payload, run_id, reverted, created_at
       FROM messages WHERE conversation_id = ? AND reverted = 0 ORDER BY created_at ASC, rowid ASC`,
    )
    .all(sourceConvId) as MessageRow[];
  const limitIdx = upToMessageId ? rows.findIndex((r) => r.id === upToMessageId) : rows.length - 1;
  const slice = limitIdx >= 0 ? rows.slice(0, limitIdx + 1) : rows;
  const insert = getDb().prepare(
    `INSERT INTO messages (id, conversation_id, role, content, status, tool_name, tool_payload, run_id, reverted, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)`,
  );
  for (const r of slice) {
    insert.run(crypto.randomUUID(), targetConvId, r.role, r.content, r.status, r.tool_name, r.tool_payload, r.run_id, r.created_at);
  }
}

export function addMessage(input: {
  id?: string;
  conversation_id: string;
  role: WorkRole;
  content?: string;
  status?: WorkMessage["status"];
  tool_name?: string | null;
  tool_payload?: Record<string, unknown> | null;
  run_id?: string | null;
}): WorkMessage {
  const message: WorkMessage = {
    id: input.id ?? crypto.randomUUID(),
    conversation_id: input.conversation_id,
    role: input.role,
    content: input.content ?? "",
    status: input.status ?? "completed",
    tool_name: input.tool_name ?? null,
    tool_payload: input.tool_payload ?? null,
    run_id: input.run_id ?? null,
    created_at: now(),
  };
  getDb()
    .prepare(
      `INSERT INTO messages (id, conversation_id, role, content, status, tool_name, tool_payload, run_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(
      message.id,
      message.conversation_id,
      message.role,
      message.content,
      message.status,
      message.tool_name,
      message.tool_payload ? JSON.stringify(message.tool_payload) : null,
      message.run_id,
      message.created_at,
    );
  touchConversation(message.conversation_id);
  return message;
}

export function updateMessage(
  id: string,
  patch: Partial<Pick<WorkMessage, "content" | "status" | "tool_name" | "tool_payload" | "run_id">>,
): void {
  const fields: string[] = [];
  const values: unknown[] = [];
  if (patch.content !== undefined) {
    fields.push("content = ?");
    values.push(patch.content);
  }
  if (patch.status !== undefined) {
    fields.push("status = ?");
    values.push(patch.status);
  }
  if (patch.tool_name !== undefined) {
    fields.push("tool_name = ?");
    values.push(patch.tool_name);
  }
  if (patch.tool_payload !== undefined) {
    fields.push("tool_payload = ?");
    values.push(patch.tool_payload ? JSON.stringify(patch.tool_payload) : null);
  }
  if (patch.run_id !== undefined) {
    fields.push("run_id = ?");
    values.push(patch.run_id);
  }
  if (!fields.length) return;
  values.push(id);
  getDb().prepare(`UPDATE messages SET ${fields.join(", ")} WHERE id = ?`).run(...values);
}

export function appendMessageContent(id: string, delta: string): void {
  getDb().prepare(`UPDATE messages SET content = content || ? WHERE id = ?`).run(delta, id);
}

export function deleteMessage(id: string): void {
  getDb().prepare(`DELETE FROM messages WHERE id = ?`).run(id);
}

export function findRunningTool(conversationId: string, tool: string, toolCallId?: string | null): WorkMessage | null {
  const rows = getDb()
    .prepare(
      `SELECT id, conversation_id, role, content, status, tool_name, tool_payload, run_id, reverted, created_at
       FROM messages WHERE conversation_id = ? AND role = 'tool' AND status = 'running' AND reverted = 0 ORDER BY created_at DESC, rowid DESC LIMIT 20`,
    )
    .all(conversationId) as MessageRow[];
  if (toolCallId) {
    for (const row of rows) {
      const parsed = toMessage(row);
      if (parsed.tool_payload?.tool_call_id === toolCallId) return parsed;
    }
  }
  const byName = rows.find((r) => r.tool_name === tool);
  return byName ? toMessage(byName) : null;
}

export function getKv(key: string): string | null {
  const row = getDb().prepare(`SELECT value FROM kv WHERE key = ?`).get(key) as { value: string } | undefined;
  return row?.value ?? null;
}

export function setKv(key: string, value: string): void {
  getDb()
    .prepare(`INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value`)
    .run(key, value);
}

export function deleteKv(key: string): void {
  getDb().prepare(`DELETE FROM kv WHERE key = ?`).run(key);
}

export function listWorkspaces(): WorkWorkspace[] {
  return getDb()
    .prepare(`SELECT id, path, name, last_opened_at, created_at FROM workspaces ORDER BY last_opened_at DESC`)
    .all() as WorkspaceRow[];
}

export function getWorkspaceByPath(dirPath: string): WorkWorkspace | null {
  const resolved = path.resolve(dirPath);
  const row = getDb()
    .prepare(`SELECT id, path, name, last_opened_at, created_at FROM workspaces WHERE path = ?`)
    .get(resolved) as WorkspaceRow | undefined;
  return row ?? null;
}

export function upsertWorkspace(dirPath: string): WorkWorkspace {
  const resolved = path.resolve(dirPath);
  const name = path.basename(resolved) || resolved;
  const stamp = now();
  const existing = getWorkspaceByPath(resolved);
  if (existing) {
    getDb()
      .prepare(`UPDATE workspaces SET name = ?, last_opened_at = ? WHERE id = ?`)
      .run(name, stamp, existing.id);
    return { ...existing, name, last_opened_at: stamp };
  }
  const id = crypto.randomUUID();
  getDb()
    .prepare(`INSERT INTO workspaces (id, path, name, last_opened_at, created_at) VALUES (?, ?, ?, ?, ?)`)
    .run(id, resolved, name, stamp, stamp);
  return { id, path: resolved, name, last_opened_at: stamp, created_at: stamp };
}

export function removeWorkspace(dirPath: string): void {
  const resolved = path.resolve(dirPath);
  getDb().prepare(`DELETE FROM workspaces WHERE path = ?`).run(resolved);
  if (getActiveWorkspacePath() === resolved) {
    deleteKv(ACTIVE_WORKSPACE_KV);
  }
}

export function getActiveWorkspacePath(): string | null {
  const val = getKv(ACTIVE_WORKSPACE_KV);
  return val && val.trim() ? val.trim() : null;
}

export function setActiveWorkspacePath(dirPath: string | null): void {
  if (!dirPath) {
    deleteKv(ACTIVE_WORKSPACE_KV);
    return;
  }
  setKv(ACTIVE_WORKSPACE_KV, path.resolve(dirPath));
}
