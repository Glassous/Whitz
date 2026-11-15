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

export interface SecurityQuestion {
  position: number;
  question: string;
}

export interface SecurityQuestionInput {
  question: string;
  answer: string;
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