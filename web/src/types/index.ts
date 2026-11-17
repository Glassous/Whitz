export type MembershipTier = "free" | "plus" | "pro";

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_active: boolean;
  persona: string;
  email_verified_at?: string | null;
  membership_tier: MembershipTier;
  membership_expires_at: string | null;
  created_at: string;
}

export interface CreditWindow {
  limit: number | null;
  used: number;
  remaining: number | null;
  reset_at: string;
}

export interface MembershipPlan {
  tier: MembershipTier;
  label: string;
  weekly_credits: number;
  five_hour_credits: number | null;
  max_runs_per_user: number;
  chat_per_minute: number;
  run_max_seconds: number;
  summary: string;
}

export interface CreditStatus {
  tier: MembershipTier;
  tier_label: string;
  expires_at: string | null;
  anchor_at: string;
  tokens_per_credit: number;
  weekly: CreditWindow;
  five_hour: CreditWindow;
  remaining: number;
  overdrawn: boolean;
  plan: MembershipPlan;
  plans: MembershipPlan[];
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in?: number;
  refresh_expires_in?: number;
  user: User;
}

export type EmailCodePurpose = "register" | "login" | "reset_password";

export interface EmailCodeResponse {
  message: string;
  expires_in: number;
  cooldown: number;
}

export interface PlanItem {
  id: string | number | null;
  content: string;
  status: string;
  parent: string | number | null;
}

export interface Plan {
  items: PlanItem[];
}

export interface Conversation {
  id: string;
  title: string;
  plan: Plan | null;
  active_run_id: string | null;
  active_run_status: string | null;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
}

export interface ConversationSearchHit {
  conversation_id: string;
  conversation_title: string;
  message_id: string | null;
  role: "user" | "assistant" | null;
  snippet: string;
  match_in: "title" | "message";
  created_at: string;
}

export type MessageRole = "user" | "assistant" | "tool";
export type MessageStatus = "streaming" | "completed" | "failed" | "cancelled" | "running" | "waiting";

export interface ReasoningTool {
  name: string;
  args?: string;
  result?: string;
  status?: string;
}

export interface ReasoningBlock {
  step: number | null;
  step_id?: string | null;
  title: string;
  text: string;
  content?: string;
  tools?: ReasoningTool[];
}

export type FileCategory = "document" | "spreadsheet" | "code" | "image";

export interface ConversationFile {
  id: string;
  conversation_id: string;
  filename: string;
  ext: string;
  mime_type: string;
  category: FileCategory | string;
  size_bytes: number;
  status: "pending" | "ready" | "failed" | string;
  created_at: string;
  updated_at: string;
}

export interface FileAttachmentMeta {
  id: string;
  filename: string;
  ext: string;
  category: string;
  size_bytes: number;
}

export type UploadTaskStatus = "signing" | "uploading" | "completing" | "error";

export interface UploadTask {
  localId: string;
  filename: string;
  ext: string;
  category: string;
  sizeBytes: number;
  progress: number;
  status: UploadTaskStatus;
  error?: string | null;
  file?: File;
}

export type TaskPanelTab = "steps" | "files";

export interface ToolPayload {
  args?: unknown;
  result?: unknown;
  duration?: number;
  error?: string | null;
  status?: string;
  usage?: unknown;
  runtime?: unknown;
  reasoning?: ReasoningBlock[];
  plan?: Plan | null;
  attachments?: FileAttachmentMeta[];
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  tool_name: string | null;
  tool_payload: ToolPayload | null;
  status: MessageStatus;
  hermes_run_id: string | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface AgentStatus {
  ready: boolean;
  status: string;
  version?: string | null;
  model?: string | null;
  enabled_toolsets?: string[];
  detail?: unknown;
}

export interface PendingControl {
  kind: "approval" | "clarify";
  request_id: string | null;
  execution_generation: number | null;
  tool?: string | null;
  preview?: string | null;
}