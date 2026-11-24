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

export interface WorkConversationSummary {
  additions: number;
  deletions: number;
  files: number;
}

export interface WorkConversation {
  id: string;
  title: string;
  opencode_session_id?: string | null;
  workspace_path: string | null;
  is_pinned: boolean;
  model_ref?: string | null;
  agent_name?: string | null;
  variant?: string | null;
  share_url?: string | null;
  worktree_name?: string | null;
  worktree_branch?: string | null;
  summary?: WorkConversationSummary | null;
  total_cost?: number;
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
  reverted?: boolean;
  created_at: string;
}

export interface WorkTokenUsage {
  input: number;
  output: number;
  reasoning: number;
  cache_read: number;
  cache_write: number;
  cost: number;
  total: number;
  context_limit: number | null;
}

export interface WorkClarifyOption {
  label: string;
  description?: string;
}

export interface WorkClarifyQuestion {
  id: string;
  header?: string;
  question: string;
  options: WorkClarifyOption[];
  multiple?: boolean;
  custom?: boolean;
}

export interface WorkPendingControl {
  kind: "approval" | "clarify";
  request_id: string;
  execution_generation: number;
  tool: string | null;
  preview: unknown;
  choices?: string[] | null;
  patterns?: string[];
  always_patterns?: string[];
  metadata?: Record<string, unknown> | null;
  questions?: WorkClarifyQuestion[] | null;
}

export type WorkTimelineKind = "thinking" | "commentary" | "tool" | "subagent" | "patch" | "retry" | "compaction";

export interface WorkTimelineItem {
  id: string;
  kind: WorkTimelineKind;
  title?: string | null;
  text?: string;
  tool?: string | null;
  call_id?: string | null;
  args?: unknown;
  result?: unknown;
  error?: string | null;
  duration?: number | null;
  status?: "running" | "completed" | "failed";
  child_session_id?: string | null;
  files?: string[];
  attempt?: number;
  next_retry_at?: number | null;
}

export interface WorkSessionRetryState {
  attempt: number;
  message: string;
  next: number;
  action?: {
    reason?: string;
    provider?: string;
    title?: string;
    message?: string;
    label?: string;
    link?: string;
  } | null;
}

export interface WorkActiveRunSnapshot {
  conversation_id: string;
  run_id: string;
  assistant_id: string;
  status: "streaming" | "waiting";
  content: string;
  reasoning: Array<Record<string, unknown>>;
  timeline?: WorkTimelineItem[];
  plan: Record<string, unknown> | null;
  pending_control: WorkPendingControl | null;
  pending_controls?: WorkPendingControl[];
  usage: WorkTokenUsage | null;
  retry?: WorkSessionRetryState | null;
}

export interface WorkConversationDetail {
  conversation: WorkConversation;
  messages: WorkMessage[];
  active_run_id: string | null;
  active_run_status: string | null;
  reverted_count?: number;
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
  /** null = not filtered yet (show all available); array = explicit whitelist shown in composer */
  enabled_models: string[] | null;
  default_composer_model: string;
  default_agent: string;
  default_variant: string;
  full_command_mode: boolean;
  desktop_notifications: boolean;
  auto_sync_cli_sessions: boolean;
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
  enabled_models?: string[] | null;
  default_composer_model?: string;
  default_agent?: string;
  default_variant?: string;
  full_command_mode?: boolean;
  desktop_notifications?: boolean;
  auto_sync_cli_sessions?: boolean;
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
  variants?: string[];
  context_limit?: number | null;
  supports_image?: boolean;
  supports_pdf?: boolean;
  reasoning?: boolean;
}

export interface OpenCodeProviderModelInput {
  id: string;
  name?: string;
  variants?: Record<string, Record<string, unknown>>;
}

export interface OpenCodeProviderInput {
  id: string;
  name?: string;
  npm: string;
  baseURL?: string;
  apiKey?: string;
  clearApiKey?: boolean;
  models: OpenCodeProviderModelInput[];
  setCacheKey?: boolean;
}

export interface WorkAgentInfo {
  name: string;
  description?: string;
  mode: "primary" | "subagent" | "all";
  native?: boolean;
  hidden?: boolean;
  color?: string;
  model?: { providerID: string; modelID: string } | null;
  variant?: string | null;
}

export interface WorkCommandInfo {
  name: string;
  description?: string;
  agent?: string;
  model?: string;
  source?: "command" | "mcp" | "skill";
  template?: string;
  hints?: string[];
}

export interface WorkMcpServerConfig {
  type: "local" | "remote";
  command?: string[];
  environment?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface WorkMcpServerInfo {
  name: string;
  status: "connected" | "disabled" | "failed" | "needs_auth" | "needs_client_registration" | "configured";
  error?: string | null;
  config: WorkMcpServerConfig | null;
}

export interface WorkMcpServerInput {
  name: string;
  type: "local" | "remote";
  command?: string[];
  environment?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface WorkLspStatus {
  id: string;
  name: string;
  root: string;
  status: "connected" | "error";
}

export interface WorkFormatterStatus {
  name: string;
  extensions: string[];
  enabled: boolean;
}

export interface WorkSessionDiffItem {
  file: string;
  patch?: string;
  before?: string;
  after?: string;
  additions?: number;
  deletions?: number;
  status?: "added" | "deleted" | "modified";
}

export interface WorkPtyInfo {
  id: string;
  title: string;
  command: string;
  args: string[];
  cwd: string;
  status: "running" | "exited";
  pid: number;
  exitCode?: number | null;
}

export interface WorkShellOption {
  name: string;
  path: string;
  args?: string[];
  is_default?: boolean;
}

export interface WorkPtyConnectInfo {
  pty_id: string;
  ws_url: string;
  ticket: string;
}

export interface WorkWorktreeInfo {
  name: string;
  branch?: string | null;
  directory: string;
}

export interface WorkProviderAuthMethod {
  type: "oauth" | "api";
  label: string;
  prompts?: Array<{
    type: string;
    key: string;
    message: string;
    placeholder?: string;
  }>;
}

export interface WorkProviderOAuthStart {
  url: string;
  method: "auto" | "code";
  instructions: string;
}

export interface WorkProviderCatalogItem {
  id: string;
  name: string;
  connected: boolean;
  source?: string;
  model_count: number;
  sample_models: string[];
  auth_methods: WorkProviderAuthMethod[];
  has_oauth: boolean;
  has_api_key: boolean;
}

export interface WorkFindMatch {
  path: string;
  line_number: number;
  lines: string;
  submatches?: Array<{ match: string; start: number; end: number }>;
}

export interface WorkSymbolMatch {
  name: string;
  kind: number;
  path: string;
  line: number;
}

export interface WorkRemoteSessionSummary {
  id: string;
  title: string;
  directory: string;
  parent_id?: string | null;
  created_at: string;
  updated_at: string;
  share_url?: string | null;
  summary?: WorkConversationSummary | null;
  cost?: number;
  linked_conversation_id: string | null;
}

export interface WorkGlobalEvent {
  type: string;
  directory?: string | null;
  properties: Record<string, unknown>;
}

export interface WorkSessionPrefsPatch {
  model_ref?: string | null;
  agent_name?: string | null;
  variant?: string | null;
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
  mcp_servers: WorkMcpServerInfo[];
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
  model_ref?: string | null;
  agent_name?: string | null;
  variant?: string | null;
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
