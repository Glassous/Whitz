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
  ai_posts_enabled?: boolean;
  ai_posts_consented_at?: string | null;
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
  max_tool_iterations?: number;
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
  is_scheduled?: boolean;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
}

export interface ConversationSearchHit {
  conversation_id: string;
  conversation_kind?: ConversationKind;
  conversation_title: string;
  is_scheduled?: boolean;
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
  conversation_title?: string | null;
  conversation_kind?: string | null;
  filename: string;
  ext: string;
  mime_type: string;
  category: FileCategory | string;
  size_bytes: number;
  status: "pending" | "ready" | "failed" | string;
  index_status?: "pending" | "indexing" | "ready" | "partial" | "failed" | string;
  indexed_chunks?: number;
  summary?: string;
  index_error?: string | null;
  indexed_at?: string | null;
  source: "user" | "assistant" | string;
  is_global: boolean;
  message_id?: string | null;
  qa_snippet?: string | null;
  turn_role?: "user" | "assistant" | string | null;
  preview_url?: string | null;
  thumb_url?: string | null;
  preview_expires_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeliverableTarget {
  fileId: string;
  filename: string;
  title?: string;
  summary?: string;
  conversationId?: string | null;
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

export type RagMode = "auto" | "files_only" | "off";

export interface RagScope {
  mode: RagMode;
  include_memory: boolean;
  include_chats: boolean;
  file_ids?: string[];
  collections?: string[];
}

export interface CitationItem {
  citation_id: string;
  source_type: "file" | "memory" | "chat_digest" | "chat_turn" | string;
  source_id: string;
  chunk_id?: string | null;
  title: string;
  subtitle?: string;
  snippet: string;
  score?: number;
  confidence?: "high" | "medium" | "low" | string;
  metadata?: Record<string, any>;
}

export interface UnifiedFileSearchHit {
  type: "file";
  file_id: string;
  filename: string;
  locator: string;
  section_path?: string;
  chunk_type?: string;
  snippet: string;
  score: number;
  confidence?: string;
  conversation_id?: string | null;
}

export interface UnifiedMemorySearchHit {
  type: "memory";
  entry_id: string;
  title: string;
  collection: string;
  collection_name: string;
  tags: string[];
  snippet: string;
  content: string;
  score: number;
  confidence?: string;
  timestamp?: string | null;
}

export interface UnifiedChatSearchHit {
  type: "chat";
  match_in: "digest" | "semantic_turn" | "message" | "title" | string;
  conversation_id: string;
  conversation_kind?: ConversationKind | string;
  conversation_title: string;
  message_id?: string | null;
  role?: "user" | "assistant" | null;
  snippet: string;
  score: number;
  confidence?: string;
  created_at?: string | null;
}

export interface UnifiedSearchResponse {
  query: string;
  files: UnifiedFileSearchHit[];
  memories: UnifiedMemorySearchHit[];
  chats: UnifiedChatSearchHit[];
  total: number;
  diagnostics?: Record<string, any>;
}

export interface LibraryContentSearchHit {
  file_id: string;
  filename: string;
  locator: string;
  section_path?: string;
  chunk_type?: string;
  snippet: string;
  content: string;
  score: number;
  confidence?: string;
}

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
  citations?: CitationItem[];
  rag_metrics?: Record<string, any> | null;
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

export interface ClarifyQuestionItem {
  id: string;
  question: string;
  options: string[];
  multiple: boolean;
  allow_custom: boolean;
  placeholder?: string | null;
}

export interface ClarifyDetail {
  question?: string | null;
  options?: string[];
  multiple?: boolean;
  questions?: ClarifyQuestionItem[];
}

export interface ClarifyAnswerItem {
  id?: string | null;
  question?: string | null;
  selected: string[];
  text: string;
}

export interface ClarifySubmitPayload {
  answer: string;
  answers?: ClarifyAnswerItem[];
}

export interface PendingControl {
  kind: "approval" | "clarify";
  request_id: string | null;
  execution_generation: number | null;
  tool?: string | null;
  preview?: string | null;
  detail?: Record<string, any> | null;
  clarify?: ClarifyDetail | null;
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

export interface MemoryCollection {
  id: string;
  slug: string;
  name: string;
  description: string;
  kind: "system" | "custom" | string;
  enabled: boolean;
  entry_count: number;
  char_count: number;
  char_limit: number;
  max_entries: number;
  sort_order: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface MemoryEntry {
  id: string;
  collection_id?: string | null;
  collection_name?: string | null;
  title?: string;
  content: string;
  tags?: string[];
  target?: string;
  category?: string | null;
  source?: "user" | "assistant" | "agent" | "manual" | string;
  is_pinned?: boolean;
  priority?: number;
  access_count?: number;
  last_accessed_at?: string | null;
  supersedes_id?: string | null;
  char_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ConversationWorkingGoal {
  title: string;
  status: "in_progress" | "blocked" | "pending" | string;
  updated?: string;
}

export interface ConversationWorkingDecision {
  decision: string;
  date?: string;
  reason?: string;
}

export interface ConversationWorkingState {
  active_goals: ConversationWorkingGoal[];
  recent_decisions: ConversationWorkingDecision[];
  open_questions: string[];
  key_entities: Record<string, string>;
}

export interface ConversationEpisodeItem {
  id: string;
  conversation_id: string;
  conversation_kind: string;
  episode_index: number;
  topic: string;
  summary: string;
  key_facts: string[];
  entities: string[];
  start_msg_id?: string | null;
  end_msg_id?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  message_count: number;
  created_at?: string | null;
}

export interface ConversationContextState {
  conversation_id: string;
  conversation_kind: string;
  working_state: ConversationWorkingState | null;
  rolling_summary?: string | null;
  working_state_updated_at?: string | null;
  episodes: ConversationEpisodeItem[];
  pinned_memories_count: number;
}

export interface MemorySearchHit {
  id: string;
  collection_id?: string | null;
  target: string;
  collection_name: string;
  title: string;
  content: string;
  tags: string[];
  source: string;
  score: number;
}

export interface MemorySearchResponse {
  query: string;
  collection?: string | null;
  count: number;
  results: MemorySearchHit[];
}

export interface MemoryPendingItem {
  id: string;
  collection_id?: string | null;
  action: "add" | "replace" | "remove" | "create" | "update" | "delete" | string;
  target?: string;
  title?: string;
  tags?: string[];
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
  collections?: MemoryCollection[];
  entries: MemoryEntry[];
  pending: MemoryPendingItem[];
  char_count?: number;
  char_limit?: number;
  memory_char_count?: number;
  memory_char_limit?: number;
  user_char_count?: number;
  user_char_limit?: number;
  total_char_count?: number;
  total_char_limit?: number;
  collection_limit?: number;
  pinned_count?: number;
  pinned_limit?: number;
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

export type ScheduleType = "once" | "interval" | "daily" | "weekly" | "monthly" | "cron";
export type ScheduleTargetMode = "dedicated" | "main" | "conversation";
export type ScheduleModelRoute = "auto" | "default" | "fast" | "reasoning";

export interface ScheduledTaskRun {
  id: string;
  task_id: string;
  conversation_id: string | null;
  assistant_message_id: string | null;
  run_id: string | null;
  trigger_type: "scheduled" | "manual" | string;
  status: "queued" | "running" | "completed" | "failed" | "skipped" | "cancelled" | string;
  scheduled_for: string | null;
  started_at: string;
  finished_at: string | null;
  summary: string | null;
  error: string | null;
  tokens_used: number;
}

export interface ScheduledTask {
  id: string;
  conversation_id: string | null;
  target_mode: ScheduleTargetMode;
  name: string;
  prompt: string;
  schedule_type: ScheduleType;
  schedule_config: Record<string, any>;
  schedule_description: string;
  timezone: string;
  model_route: ScheduleModelRoute;
  skill_names: string[];
  enabled: boolean;
  status: "active" | "paused" | "completed" | "error" | string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  last_error: string | null;
  run_count: number;
  consecutive_failures: number;
  max_runs: number | null;
  source: string;
  created_at: string;
  updated_at: string;
  runs?: ScheduledTaskRun[];
}

export interface ScheduledTaskPendingItem {
  id: string;
  target_task_id?: string | null;
  conversation_id?: string | null;
  action: "create" | "update" | "pause" | "resume" | "delete" | string;
  payload: Record<string, any>;
  schedule_description?: string;
  reason?: string | null;
  status?: string;
  created_at?: string | null;
}

export interface ScheduleQuota {
  tier: MembershipTier | string;
  max_active_tasks: number;
  active_count: number;
  min_interval_minutes: number;
}

export interface ScheduleOverview {
  tasks: ScheduledTask[];
  pending: ScheduledTaskPendingItem[];
  quota: ScheduleQuota;
}

export interface SchedulePreviewResult {
  valid: boolean;
  schedule_description: string;
  next_runs: string[];
  error?: string | null;
}

export type PostKind = "opinion" | "digest" | "insight" | "inspiration" | "note" | string;

export interface PostWebSource {
  title: string;
  url: string;
  site_name?: string;
  published_at?: string;
}

export interface PostCommentItem {
  id: string;
  post_id: string;
  author_type: "user" | "ai";
  content: string;
  reply_to_id?: string | null;
  reply_to_author_type?: "user" | "ai" | null;
  reply_to_excerpt?: string | null;
  ai_liked: boolean;
  created_at: string;
}

export interface PostItem {
  id: string;
  author_type: "ai" | "user";
  post_kind: PostKind;
  title: string;
  content: string;
  tags: string[];
  web_sources: PostWebSource[];
  source_collection_id?: string | null;
  source_collection_name?: string | null;
  source_memory_ids: string[];
  memory_entry_id?: string | null;
  is_liked: boolean;
  ai_liked: boolean;
  is_bookmarked: boolean;
  conversation_id?: string | null;
  comment_count: number;
  comments: PostCommentItem[];
  created_at: string;
  updated_at: string;
}

export interface PostQuotaSummary {
  ai_posts_enabled: boolean;
  ai_posts_consented_at?: string | null;
  memory_enabled: boolean;
  tier: MembershipTier | string;
  tier_label: string;
  max_daily_cap: number;
  memory_entry_count: number;
  active_collection_count: number;
  estimated_daily_count: number;
  today_generated_count: number;
  today_status?: string | null;
  local_date: string;
}

export interface PostListResponse {
  items: PostItem[];
  next_cursor: string | null;
  quota: PostQuotaSummary;
}

export interface PostCommentCreateResponse {
  comment: PostCommentItem;
  ai_reply_scheduled: boolean;
}

export interface PostDiscussResponse {
  conversation_id: string;
  prefill_prompt: string;
}