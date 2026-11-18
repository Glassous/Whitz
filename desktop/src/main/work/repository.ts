import crypto from "node:crypto";
import { getDb } from "./db";
import type { WorkConversation, WorkConversationDetail, WorkMessage, WorkRole } from "../../shared/work-types";

interface ConversationRow {
  id: string;
  title: string;
  hermes_session_id: string | null;
  created_at: string;
  updated_at: string;
}

interface MessageRow {
  id: string;
  conversation_id: string;
  role: WorkRole;
  content: string;
  status: WorkMessage["status"];
  tool_name: string | null;
  tool_payload: string | null;
  hermes_run_id: string | null;
  created_at: string;
}

function now(): string {
  return new Date().toISOString();
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
    hermes_run_id: row.hermes_run_id,
    created_at: row.created_at,
  };
}

export function listConversations(): WorkConversation[] {
  const rows = getDb()
    .prepare(
      `SELECT id, title, hermes_session_id, created_at, updated_at
       FROM conversations WHERE archived = 0 ORDER BY updated_at DESC`,
    )
    .all() as ConversationRow[];
  return rows.map((row) => ({
    id: row.id,
    title: row.title,
    created_at: row.created_at,
    updated_at: row.updated_at,
  }));
}

export function createConversation(title = "新的本地对话"): WorkConversation {
  const id = crypto.randomUUID();
  const stamp = now();
  getDb()
    .prepare(
      `INSERT INTO conversations (id, title, hermes_session_id, created_at, updated_at, archived)
       VALUES (?, ?, NULL, ?, ?, 0)`,
    )
    .run(id, title.trim() || "新的本地对话", stamp, stamp);
  return { id, title: title.trim() || "新的本地对话", created_at: stamp, updated_at: stamp };
}

export function getConversationMeta(id: string): ConversationRow | null {
  const row = getDb()
    .prepare(`SELECT id, title, hermes_session_id, created_at, updated_at FROM conversations WHERE id = ? AND archived = 0`)
    .get(id) as ConversationRow | undefined;
  return row ?? null;
}

export function getConversation(id: string): WorkConversationDetail | null {
  const conversation = getConversationMeta(id);
  if (!conversation) return null;
  const rows = getDb()
    .prepare(`SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC`)
    .all(id) as MessageRow[];
  const messages = rows.map(toMessage);
  const lastAssistantRun = [...messages].reverse().find((m) => m.role === "assistant")?.hermes_run_id ?? null;
  return {
    conversation: {
      id: conversation.id,
      title: conversation.title,
      created_at: conversation.created_at,
      updated_at: conversation.updated_at,
    },
    messages,
    active_run_id: lastAssistantRun,
    active_run_status: null,
  };
}

export function renameConversation(id: string, title: string): void {
  getDb()
    .prepare(`UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?`)
    .run(title.trim().slice(0, 120) || "未命名对话", now(), id);
}

export function deleteConversation(id: string): void {
  getDb().prepare(`DELETE FROM conversations WHERE id = ?`).run(id);
}

export function setHermesSession(id: string, sessionId: string): void {
  getDb()
    .prepare(`UPDATE conversations SET hermes_session_id = ?, updated_at = ? WHERE id = ?`)
    .run(sessionId, now(), id);
}

export function touchConversation(id: string): void {
  getDb().prepare(`UPDATE conversations SET updated_at = ? WHERE id = ?`).run(now(), id);
}

export function addMessage(input: {
  conversation_id: string;
  role: WorkRole;
  content?: string;
  status?: WorkMessage["status"];
  tool_name?: string | null;
  tool_payload?: Record<string, unknown> | null;
  hermes_run_id?: string | null;
  id?: string;
}): WorkMessage {
  const message: WorkMessage = {
    id: input.id ?? crypto.randomUUID(),
    conversation_id: input.conversation_id,
    role: input.role,
    content: input.content ?? "",
    status: input.status ?? "completed",
    tool_name: input.tool_name ?? null,
    tool_payload: input.tool_payload ?? null,
    hermes_run_id: input.hermes_run_id ?? null,
    created_at: now(),
  };
  getDb()
    .prepare(
      `INSERT INTO messages (id, conversation_id, role, content, status, tool_name, tool_payload, hermes_run_id, created_at)
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
      message.hermes_run_id,
      message.created_at,
    );
  touchConversation(message.conversation_id);
  return message;
}

export function updateMessage(
  id: string,
  patch: Partial<Pick<WorkMessage, "content" | "status" | "tool_name" | "tool_payload" | "hermes_run_id">>,
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
  if (patch.hermes_run_id !== undefined) {
    fields.push("hermes_run_id = ?");
    values.push(patch.hermes_run_id);
  }
  if (!fields.length) return;
  values.push(id);
  getDb().prepare(`UPDATE messages SET ${fields.join(", ")} WHERE id = ?`).run(...values);
}

export function appendMessageContent(id: string, delta: string): void {
  getDb().prepare(`UPDATE messages SET content = content || ? WHERE id = ?`).run(delta, id);
}

export function getMessage(id: string): WorkMessage | null {
  const row = getDb().prepare(`SELECT * FROM messages WHERE id = ?`).get(id) as MessageRow | undefined;
  return row ? toMessage(row) : null;
}

export function findRunningTool(conversationId: string, tool: string): WorkMessage | null {
  const row = getDb()
    .prepare(
      `SELECT * FROM messages WHERE conversation_id = ? AND role = 'tool' AND tool_name = ? AND status = 'running' ORDER BY created_at DESC LIMIT 1`,
    )
    .get(conversationId, tool) as MessageRow | undefined;
  return row ? toMessage(row) : null;
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

export function conversationCount(): number {
  const row = getDb().prepare(`SELECT COUNT(*) AS count FROM conversations WHERE archived = 0`).get() as { count: number };
  return row.count;
}
