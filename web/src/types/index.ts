export type MembershipTier = "free" | "plus" | "pro";

export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string | null;
  assistant_name?: string;
  assistant_avatar_url?: string | null;
  bio?: string;
  gender?: string | null;
  birthday?: string | null;
  phone?: string | null;
  location?: string | null;
  occupation?: string | null;
  website?: string | null;
  preferred_language?: string;
  timezone?: string;
  role: "user" | "admin";
  is_active: boolean;
  persona: string;
  email_verified_at?: string | null;
  membership_tier: MembershipTier;
  membership_expires_at: string | null;
  profile_context_enabled: boolean;
  profile_context_consented_at: string | null;
  memory_enabled: boolean;
  memory_consented_at: string | null;
  memory_require_confirm: boolean;
  ai_reactions_enabled?: boolean;
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

export type ConversationKind = "main" | "side";

export interface Conversation {
  id: string;
  kind?: ConversationKind;
  title: string;
  plan: Plan | null;
  active_run_id: string | null;
  active_run_status: string | null;
  pending_control?: Record<string, any> | null;
  is_pinned: boolean;
  pinned_at: string | null;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
}

export interface ConversationSearchHit {
  conversation_id: string;
  conversation_kind?: ConversationKind;
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
  call_id?: string | null;
  args?: string;
  result?: string;
  status?: string;
  duration_ms?: number | null;
  error?: string | null;
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
  conversation_id: string | null;
  filename: string;
  ext: string;
  mime_type: string;
  category: FileCategory | string;
  size_bytes: number;
  status: "pending" | "ready" | "failed" | string;
  index_status?: "pending" | "indexing" | "ready" | "partial" | "failed" | string;
  indexed_chunks?: number;
  source: "user" | "assistant" | string;
  is_global: boolean;
  message_id?: string | null;
  preview_url?: string | null;
  thumb_url?: string | null;
  preview_expires_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface LibraryFileItem extends ConversationFile {
  conversation_title?: string | null;
}

export interface FileAttachmentMeta {
  id: string;
  filename: string;
  ext: string;
  category: string;
  size_bytes: number;
}

export interface WorkspaceArtifactMeta {
  id: string;
  filename: string;
  ext: string;
  category: FileCategory | string;
  size_bytes: number;
  mime_type?: string;
  source?: "assistant" | "user" | string;
  is_global?: boolean;
  message_id?: string | null;
  preview_url?: string | null;
  thumb_url?: string | null;
  preview_expires_at?: string | null;
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
  localPreviewUrl?: string | null;
}

export type TaskPanelTab = "steps" | "files";

export type PreviewTarget =
  | {
      kind: "file";
      file: ConversationFile;
      previewUrl?: string | null;
      content?: string | null;
    }
  | {
      kind: "html";
      html: string;
      title?: string;
    };

export interface ToolPayload {
  call_id?: string | null;
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
  skills?: string[];
  artifacts?: WorkspaceArtifactMeta[];
}

export type UserReactionType = "like" | "love" | "insightful" | "celebrate" | "dislike";
export type AiReactionType = "like" | "love" | "sparkle" | "insightful";

export interface MessageReaction {
  id: string;
  message_id: string;
  author_type: "user" | "assistant" | string;
  reaction: UserReactionType | AiReactionType | string;
  reason_code?: string | null;
  comment?: string | null;
  created_at: string;
}

export interface UserFeedbackItem {
  id: string;
  user_id: string;
  rating: number;
  sentiment: "positive" | "neutral" | "negative" | string;
  category: "general" | "quality" | "speed" | "ui" | "feature" | "bug" | string;
  content: string;
  status: "new" | "reviewed" | "resolved" | string;
  admin_note?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  tool_name: string | null;
  tool_payload: ToolPayload | null;
  status: MessageStatus;
  run_id: string | null;
  created_at: string;
  reactions?: MessageReaction[];
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

export interface SkillItem {
  name: string;
  title?: string | null;
  description: string;
  category?: string | null;
  enabled: boolean;
  source?: "builtin" | "user" | "github" | "assistant" | "custom" | string;
  content?: string | null;
  tags?: string[];
  repo_url?: string | null;
  path?: string | null;
  editable?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SkillPendingItem {
  id: string;
  name: string;
  action: "create" | "update" | "delete" | string;
  source?: string;
  description?: string | null;
  category?: string | null;
  content: string;
  reason?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  status?: "pending" | "approved" | "rejected" | string;
  created_at?: string | null;
  resolved_at?: string | null;
}

export interface MemoryEntry {
  id: string;
  content: string;
  target?: "memory" | "user" | string;
  category?: string | null;
  source?: "user" | "assistant" | "manual" | string;
  char_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MemoryPendingItem {
  id: string;
  action: "add" | "replace" | "remove" | "create" | "update" | "delete" | string;
  target?: "memory" | "user" | string;
  content: string;
  old_content?: string | null;
  category?: string | null;
  reason?: string | null;
  conversation_id?: string | null;
  message_id?: string | null;
  status?: "pending" | "approved" | "rejected" | string;
  created_at?: string | null;
  resolved_at?: string | null;
}

export interface MemoryOverview {
  memory_enabled: boolean;
  memory_consented_at: string | null;
  memory_require_confirm: boolean;
  profile_context_enabled?: boolean;
  profile_context_consented_at?: string | null;
  entries: MemoryEntry[];
  pending: MemoryPendingItem[];
  char_count?: number;
  char_limit?: number;
  memory_char_count?: number;
  memory_char_limit?: number;
  user_char_count?: number;
  user_char_limit?: number;
}

export interface UserSessionItem {
  session_id: string;
  user_agent: string | null;
  client_ip: string | null;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
  is_current: boolean;
}