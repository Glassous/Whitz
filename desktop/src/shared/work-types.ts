export type WorkRole = "user" | "assistant" | "tool";

export interface WorkConversation {
  id: string;
  title: string;
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
  hermes_run_id: string | null;
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

export type ProviderProtocol = "builtin" | "openai" | "anthropic" | "google" | "custom";

export interface WorkModelSettings {
  protocol: ProviderProtocol;
  base_url: string;
  model: string;
  /** Never returned to the renderer; only indicates whether a key is stored. */
  api_key_set: boolean;
  supports_vision: boolean;
  approvals: "smart" | "manual" | "off";
  max_turns: number;
}

export interface WorkSettings {
  version: 1;
  model: WorkModelSettings;
  updated_at: string;
}

export interface WorkSettingsPatch {
  protocol?: ProviderProtocol;
  base_url?: string;
  model?: string;
  supports_vision?: boolean;
  approvals?: "smart" | "manual" | "off";
  max_turns?: number;
  api_key?: string;
}

export interface ProviderPreset {
  protocol: ProviderProtocol;
  label: string;
  base_url: string;
  models: string[];
  hint: string;
}

export interface RuntimeStatus {
  installed: boolean;
  running: boolean;
  state: "idle" | "installing" | "starting" | "ready" | "stopped" | "error" | "disabled";
  version: string | null;
  latest_version: string | null;
  port: number | null;
  home_dir: string | null;
  detail: string | null;
  model: string | null;
  installed_at: string | null;
  log_path: string | null;
}

export interface RuntimeProgress {
  phase: "check" | "download" | "extract" | "configure" | "start" | "done" | "error";
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

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    protocol: "openai",
    label: "OpenAI",
    base_url: "https://api.openai.com/v1",
    models: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "o4-mini"],
    hint: "OpenAI 及所有 OpenAI 兼容端点",
  },
  {
    protocol: "anthropic",
    label: "Anthropic",
    base_url: "https://api.anthropic.com",
    models: ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
    hint: "Claude 原生协议",
  },
  {
    protocol: "google",
    label: "Google Native",
    base_url: "https://generativelanguage.googleapis.com",
    models: ["gemini-2.5-pro", "gemini-2.5-flash"],
    hint: "Gemini 原生协议",
  },
  {
    protocol: "custom",
    label: "自定义",
    base_url: "",
    models: [],
    hint: "任意 OpenAI 兼容网关（vLLM、Ollama、LM Studio 等）",
  },
];
