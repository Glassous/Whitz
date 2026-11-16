export type MembershipTier = "free" | "plus" | "pro";

export interface User {
  id: string;
  email: string;
  display_name: string;
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
  role: "user" | "admin";
  is_active: boolean;
  hermes_profile: string;
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
