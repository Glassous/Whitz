export type WorkRole = "user" | "assistant" | "tool";

export type WorkApprovalChoice = "once" | "session" | "always" | "deny";

export interface WorkWorkspace {
  id: string;
  path: string;
  name: string;
  last_opened_at: string;
  created_at: string;
}

export interface WorkspaceEntry {
  name: string;
  rel_path: string;
  kind: "file" | "dir";
  size: number;
  mtime: string;
}

export interface WorkspaceFileContent {
  rel_path: string;
  abs_path: string;
  content: string;
  language: string;
  size: number;
  truncated: boolean;
  binary: boolean;
}

export interface WorkspaceGitChange {
  path: string;
  status: string;
  staged: boolean;
}

export interface WorkspaceGitStatus {
  is_repo: boolean;
  branch: string | null;
  changes: WorkspaceGitChange[];
}

export interface WorkSkillItem {
  name: string;
  description: string;
  source: string;
  enabled: boolean;
}

export interface WorkAttachment {
  id: string;
  name: string;
  path: string;
  kind: "image" | "file";
  size: number;
  preview_url?: string;
}

export interface WorkConversation {
  id: string;
  title: string;
  workspace_path: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkMessage {
  id: string;
  conversation_id: string;
  role: WorkRole;
  content: string;
  status: "completed" | "streaming" | "waiting" | "failed" | "cancelled" | "running";
  tool_name: string | null;
  tool_payload: Record<string, unknown> | null;
  run_id: string | null;
  created_at: string;
}

export interface WorkConversationDetail {
  conversation: WorkConversation;
  messages: WorkMessage[];
  active_run_id: string | null;
  active_run_status: string | null;
}

/** Mirror of the cloud SSE contract used by web/src/stores/chat.ts. */
export interface WorkEvent {
  event: string;
  data: Record<string, unknown>;
}

export type WorkAccessMode = "opencode_local" | "builtin";

export interface WorkModelSettings {
  mode: WorkAccessMode;
  builtin_model: string;
  custom_opencode_exe: string;
  active_model_label: string;
}

export interface WorkSettings {
  version: 2;
  model: WorkModelSettings;
  updated_at: string;
}

export interface WorkSettingsPatch {
  mode?: WorkAccessMode;
  builtin_model?: string;
  custom_opencode_exe?: string;
}

export interface LocalGatewayStatus {
  running: boolean;
  port: number | null;
  base_url: string | null;
  logged_in: boolean;
  error: string | null;
}

export type OpenCodePermissionPreset = "smart" | "allow_all" | "ask_all" | "custom";

export interface OpenCodeProviderInfo {
  id: string;
  name: string;
  npm: string;
  baseURL: string;
  source: "config" | "auth" | "env" | "bridge";
  connected: boolean;
  has_key: boolean;
  models: Array<{ id: string; name: string }>;
}

export interface OpenCodeModelOption {
  ref: string;
  label: string;
  providerID: string;
  modelID: string;
  connected: boolean;
  is_whitz: boolean;
}

export interface OpenCodeProviderInput {
  id: string;
  name?: string;
  npm: string;
  baseURL?: string;
  apiKey?: string;
  clearApiKey?: boolean;
  models: Array<{ id: string; name?: string }>;
  setCacheKey?: boolean;
}

export interface OpenCodeConfigSnapshot {
  config_file: string;
  agents_file: string;
  default_model: string;
  small_model: string;
  whitz_configured: boolean;
  whitz_bridge_active: boolean;
  whitz_base_url: string | null;
  whitz_port_matches: boolean;
  permission_preset: OpenCodePermissionPreset;
  providers: OpenCodeProviderInfo[];
  available_models: OpenCodeModelOption[];
  agents_md: string;
  raw_json: string;
}

export interface OpenCodeConfigSavePatch {
  default_model?: string;
  small_model?: string;
  permission_preset?: Exclude<OpenCodePermissionPreset, "custom">;
  agents_md?: string;
  raw_json?: string;
}

export interface OpenCodeProviderTemplate {
  id: string;
  label: string;
  npm: string;
  baseURL: string;
  models: string[];
  hint: string;
}

export const OPENCODE_PROVIDER_TEMPLATES: OpenCodeProviderTemplate[] = [
  {
    id: "openai",
    label: "OpenAI",
    npm: "@ai-sdk/openai",
    baseURL: "https://api.openai.com/v1",
    models: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "o4-mini"],
    hint: "OpenAI 官方或兼容 /v1 接口",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    npm: "@ai-sdk/anthropic",
    baseURL: "https://api.anthropic.com/v1",
    models: ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
    hint: "Claude 原生协议",
  },
  {
    id: "google",
    label: "Google Gemini",
    npm: "@ai-sdk/google",
    baseURL: "https://generativelanguage.googleapis.com/v1beta",
    models: ["gemini-2.5-pro", "gemini-2.5-flash"],
    hint: "Gemini 原生协议",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    npm: "@ai-sdk/openai-compatible",
    baseURL: "https://api.deepseek.com/v1",
    models: ["deepseek-chat", "deepseek-reasoner"],
    hint: "DeepSeek API",
  },
  {
    id: "custom",
    label: "自定义 OpenAI 兼容",
    npm: "@ai-sdk/openai-compatible",
    baseURL: "",
    models: [],
    hint: "任意 OpenAI 兼容网关 / Ollama / 中转站",
  },
];

export type RuntimeSource = "custom" | "system" | "npm" | "scoop" | "winget";

export interface RuntimeStatus {
  installed: boolean;
  running: boolean;
  state: "idle" | "starting" | "ready" | "stopped" | "error" | "disabled";
  version: string | null;
  latest_version: string | null;
  port: number | null;
  home_dir: string | null;
  exe_path: string | null;
  source: RuntimeSource | null;
  workspace_path: string | null;
  detail: string | null;
  model: string | null;
  installed_at: string | null;
  log_path: string | null;
  gateway: LocalGatewayStatus;
}

export interface RuntimeProgress {
  phase: "check" | "configure" | "start" | "done" | "error";
  percent: number;
  message: string;
  log_line?: string;
}

export interface DesktopInfo {
  version: string;
  platform: string;
  arch: string;
  apiBase: string;
  online: boolean;
  loggedIn: boolean;
  workModeEnabled: boolean;
}

export interface DesktopUser {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string | null;
  role?: string;
  membership_tier?: string;
}

export interface DesktopSession {
  user: DesktopUser;
  access_token: string;
  expires_in: number;
}

export interface WorkSendInput {
  conversation_id: string;
  content: string;
  skill_names?: string[];
}

export interface WorkRunRef {
  conversation_id: string;
  run_id: string;
}

export interface ConnectivityState {
  online: boolean;
  checked_at: string;
  latency_ms: number | null;
  forced_offline: boolean;
}
