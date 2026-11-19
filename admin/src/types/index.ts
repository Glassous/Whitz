export type MembershipTier = "free" | "plus" | "pro";

export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string | null;
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
  membership_tier: MembershipTier;
  membership_expires_at: string | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in?: number;
  refresh_expires_in?: number;
  user: User;
}

export interface CreditSummary {
  tier: MembershipTier;
  tier_label: string;
  expires_at: string | null;
  remaining: number;
  weekly_used: number;
  weekly_limit: number;
  five_hour_used: number;
  five_hour_limit: number | null;
  week_reset_at: string;
  five_hour_reset_at: string;
  overdrawn: boolean;
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

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  avatar_url?: string | null;
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
  agent_namespace: string;
  membership_tier: MembershipTier;
  membership_expires_at: string | null;
  credits: CreditSummary | null;
  created_at: string;
}

export interface AdminUserList {
  items: AdminUser[];
  total: number;
  page: number;
  page_size: number;
}

export interface InviteCode {
  id: string;
  code: string;
  tier: "plus" | "pro";
  duration_days: number;
  max_uses: number;
  used_count: number;
  expires_at: string | null;
  note: string | null;
  is_active: boolean;
  created_at: string;
}

export interface InviteCodeList {
  items: InviteCode[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuditLog {
  id: number;
  created_at: string;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  outcome: string;
  severity: string;
  ip: string | null;
  user_agent: string | null;
  request_id: string | null;
  session_id: string | null;
  metadata: Record<string, unknown> | null;
}

export interface AuditLogList {
  items: AuditLog[];
  total: number;
  page: number;
  page_size: number;
}

export interface Overview {
  users: { total: number; active: number; admins: number; new_today: number };
  usage_today: { day: string; messages: number; tokens: number; runs: number };
  conversations: { total: number; active_runs: number };
  audit_24h: { failures: number; critical: number };
  membership: Record<MembershipTier, number>;
  credits_today: { used: number; tokens_per_credit: number };
  plans: MembershipPlan[];
  limits: {
    max_concurrent_runs: number;
    max_concurrent_runs_per_user: number;
  };
  generated_at: string;
}

export interface AdminAnalyticsDay {
  day: string;
  messages: number;
  tokens: number;
  credits: number;
  runs: number;
  new_users: number;
  active_users: number;
}

export interface AdminAnalyticsTopUser {
  user_id: string;
  email: string;
  display_name: string;
  membership_tier: MembershipTier;
  messages: number;
  tokens: number;
  credits: number;
  runs: number;
}

export interface AdminAnalyticsFileStats {
  total_files: number;
  total_bytes: number;
  global_files: number;
  assistant_files: number;
  pending_files: number;
}

export interface AdminAnalyticsSummary {
  total_messages: number;
  total_tokens: number;
  total_credits: number;
  total_runs: number;
  total_new_users: number;
  active_users: number;
  [key: string]: number;
}

export interface AdminAnalytics {
  days: number;
  start_day: string;
  end_day: string;
  tokens_per_credit: number;
  daily: AdminAnalyticsDay[];
  top_users: AdminAnalyticsTopUser[];
  membership_distribution: Record<string, number>;
  file_stats: AdminAnalyticsFileStats;
  summary: AdminAnalyticsSummary;
  generated_at?: string;
}

export interface AdminMonitorServices {
  postgres: boolean;
  redis: boolean;
  agent: boolean;
  cos_configured: boolean;
  smtp_configured: boolean;
}

export interface AdminActiveRun {
  conversation_id: string;
  title: string;
  user_id: string;
  user_email: string;
  user_display_name: string;
  active_run_id: string;
  active_run_status: string | null;
  last_message_at: string | null;
  duration_seconds: number;
  is_stalled: boolean;
}

export interface AdminFailureSpike {
  action: string;
  count: number;
  latest_at: string;
}

export interface AdminFailingActor {
  actor_email: string | null;
  count: number;
  latest_action: string;
}

export interface AdminFailedMessage {
  message_id: string;
  conversation_id: string;
  user_email: string;
  status: string;
  created_at: string;
}

export interface AdminMonitor {
  services: AdminMonitorServices;
  active_runs: AdminActiveRun[];
  failure_spikes_24h: AdminFailureSpike[];
  top_failing_actors_24h: AdminFailingActor[];
  recent_failed_messages: AdminFailedMessage[];
  generated_at?: string;
}

export interface UserSession {
  session_id: string;
  user_agent: string | null;
  client_ip: string | null;
  last_used_at: string | null;
  created_at: string;
  expires_at: string;
  is_current?: boolean;
}

export interface AdminLedgerItem {
  id: number;
  user_id: string;
  created_at: string;
  tokens: number;
  credits: number;
  kind: "consume" | "adjust" | string;
  tier: string | null;
  conversation_id: string | null;
  message_id: string | null;
  actor_user_id: string | null;
  actor_email: string | null;
  note: string | null;
}

export interface AdminLedgerList {
  items: AdminLedgerItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface InviteRedemption {
  id: string;
  code_id: string;
  code: string | null;
  user_id: string;
  user_email: string | null;
  tier: MembershipTier | string;
  duration_days: number;
  redeemed_at: string;
}

export interface AdminUserDetail extends AdminUser {
  persona: string;
  email_verified_at: string | null;
  credit_anchor_at: string | null;
  updated_at: string | null;
  profile_context_enabled: boolean;
  profile_context_consented_at: string | null;
  memory_enabled: boolean;
  memory_consented_at: string | null;
  memory_require_confirm: boolean;
  conversation_count: number;
  message_count: number;
  file_count: number;
  total_tokens: number;
  total_messages: number;
  total_runs: number;
  active_sessions: UserSession[];
  recent_ledger: AdminLedgerItem[];
  invite_redemptions: InviteRedemption[];
}

export interface OpsInspection {
  postgres: {
    ok: boolean;
    latency_ms: number | null;
    pgvector: boolean;
    active_connections?: number;
    total_connections?: number;
    max_connections?: number;
    connection_pct?: number;
    database_size_mb?: number;
    top_tables?: Array<{ name: string; live_rows: number; dead_rows: number }>;
  };
  redis: {
    ok: boolean;
    latency_ms: number | null;
    mode?: string;
    used_memory_mb?: number;
    maxmemory_mb?: number;
    memory_pct?: number;
    connected_clients?: number;
    hit_rate_pct?: number;
    arq_queue_depth?: number;
    arq_in_progress?: number;
  };
  agent: {
    ok: boolean;
    worker_ok: boolean;
    latency_ms: number | null;
    sandbox_mode?: string;
  };
  runtime: {
    active_runs: number;
    stuck_runs: number;
    max_concurrent_runs: number;
    run_max_seconds: number;
    runs_15m: number;
    error_rate_15m_pct: number;
    p95_latency_15m_ms: number;
    firing_alerts: number;
  };
  supported_metrics: Record<string, { label: string; unit: string }>;
  generated_at: string;
}

export interface OpsAlertRule {
  id: string;
  name: string;
  metric_key: string;
  metric_label: string;
  operator: "gt" | "gte" | "lt" | "lte" | "eq";
  threshold: number;
  window_minutes: number;
  cooldown_minutes: number;
  severity: "info" | "warning" | "critical";
  webhook_url: string | null;
  enabled: boolean;
  last_triggered_at: string | null;
  created_at: string;
}

export interface OpsAlertEvent {
  id: string;
  rule_id: string | null;
  rule_name: string;
  metric_key: string;
  current_value: number;
  threshold: number;
  severity: "info" | "warning" | "critical";
  status: "firing" | "acked" | "resolved";
  message: string;
  webhook_status: string | null;
  acked_at: string | null;
  created_at: string;
}

export interface OpsAlertsResponse {
  rules: OpsAlertRule[];
  events: OpsAlertEvent[];
  supported_metrics: Record<string, { label: string; unit: string }>;
}

export interface QuantSummary {
  window_days: number;
  latency: {
    p50_ms: number | null;
    p95_ms: number | null;
    p99_ms: number | null;
    avg_ms: number | null;
    ttft_p50_ms: number | null;
    ttft_p95_ms: number | null;
  };
  runs: {
    total: number;
    completed: number;
    failed: number;
    other: number;
    success_rate_pct: number;
    avg_tokens_per_run: number;
    total_tokens: number;
    total_credits: number;
    prompt_tokens: number;
    completion_tokens: number;
    prompt_ratio_pct: number;
  };
  daily_latency: Array<{
    day: string;
    runs: number;
    completed: number;
    failed: number;
    tokens: number;
    p50_ms: number | null;
    p95_ms: number | null;
  }>;
  generated_at: string;
}

export interface QuantModelsTools {
  window_days: number;
  routes: Array<{
    route: string;
    runs: number;
    share_pct: number;
    success_rate_pct: number;
    total_tokens: number;
    avg_tokens: number;
    p95_ms: number | null;
  }>;
  models: Array<{
    model: string;
    runs: number;
    total_tokens: number;
    avg_ms: number | null;
  }>;
  tools: Array<{
    name: string;
    calls: number;
    errors: number;
    error_rate_pct: number;
    avg_duration_ms: number;
  }>;
  skills: Array<{
    name: string;
    uses: number;
  }>;
  generated_at: string;
}

export interface QuantRetention {
  window_days: number;
  funnel: Array<{ stage: string; count: number; pct: number }>;
  cohorts: Array<{
    cohort_day: string;
    new_users: number;
    d1_pct: number | null;
    d3_pct: number | null;
    d7_pct: number | null;
  }>;
  generated_at: string;
}

export interface EvalRunItem {
  id: string;
  mode: string;
  dataset_name: string;
  total: number;
  passed: number;
  pass_rate: number;
  category_scores: Record<string, { total: number; passed: number; pass_rate: number }>;
  results: Array<Record<string, unknown>>;
  git_sha: string | null;
  triggered_by: string | null;
  created_at: string;
}

export interface QuantEvalsResponse {
  items: EvalRunItem[];
  latest: EvalRunItem | null;
  pass_rate_delta_pct: number | null;
}
