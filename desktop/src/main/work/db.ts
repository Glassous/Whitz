import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "../config";

let db: Database.Database | null = null;

export function getDb(): Database.Database {
  if (db) return db;
  const file = storagePaths().db;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  db = new Database(file);
  db.pragma("journal_mode = WAL");
  db.pragma("synchronous = NORMAL");
  db.pragma("foreign_keys = ON");
  migrate(db);
  return db;
}

function migrate(conn: Database.Database): void {
  conn.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      opencode_session_id TEXT,
      workspace_path TEXT,
      is_pinned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      archived INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY,
      conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      content TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'completed',
      tool_name TEXT,
      tool_payload TEXT,
      run_id TEXT,
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS ix_messages_conversation
      ON messages(conversation_id, created_at);

    CREATE TABLE IF NOT EXISTS workspaces (
      id TEXT PRIMARY KEY,
      path TEXT NOT NULL UNIQUE,
      name TEXT NOT NULL,
      last_opened_at TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS kv (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);

  const convCols = conn.prepare("PRAGMA table_info(conversations)").all() as Array<{ name: string }>;
  const convNames = new Set(convCols.map((c) => c.name));
  if (!convNames.has("workspace_path")) {
    conn.exec("ALTER TABLE conversations ADD COLUMN workspace_path TEXT");
  }
  if (!convNames.has("is_pinned")) {
    conn.exec("ALTER TABLE conversations ADD COLUMN is_pinned INTEGER NOT NULL DEFAULT 0");
  }
  if (!convNames.has("opencode_session_id")) {
    conn.exec("ALTER TABLE conversations ADD COLUMN opencode_session_id TEXT");
  }
  if (!convNames.has("model_ref")) {
    conn.exec("ALTER TABLE conversations ADD COLUMN model_ref TEXT");
  }
  if (!convNames.has("agent_name")) {
    conn.exec("ALTER TABLE conversations ADD COLUMN agent_name TEXT");
  }
  if (!convNames.has("variant")) {
    conn.exec("ALTER TABLE conversations ADD COLUMN variant TEXT");
  }
  conn.exec("CREATE INDEX IF NOT EXISTS ix_conversations_workspace ON conversations(workspace_path, updated_at)");

  const msgCols = conn.prepare("PRAGMA table_info(messages)").all() as Array<{ name: string }>;
  const msgNames = new Set(msgCols.map((c) => c.name));
  if (!msgNames.has("run_id")) {
    conn.exec("ALTER TABLE messages ADD COLUMN run_id TEXT");
  }
  if (!msgNames.has("reverted")) {
    conn.exec("ALTER TABLE messages ADD COLUMN reverted INTEGER NOT NULL DEFAULT 0");
  }
}

export function closeDb(): void {
  if (db) {
    db.close();
    db = null;
  }
}
