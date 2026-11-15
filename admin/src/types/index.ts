export interface User {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_active: boolean;
  persona: string;
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

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_active: boolean;
  hermes_profile: string;
  created_at: string;
}

export interface AdminUserList {
  items: AdminUser[];
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
  limits: {
    daily_message_limit: number;
    daily_token_limit: number;
    max_concurrent_runs: number;
    max_concurrent_runs_per_user: number;
  };
  generated_at: string;
}
