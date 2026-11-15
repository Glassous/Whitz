import { api } from "./client";

export type TicketAction = "send" | "reconnect" | "stop" | "approval" | "clarify";

function newNonce(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export async function chatTicketHeaders(
  convId: string,
  action: TicketAction,
): Promise<Record<string, string>> {
  const nonce = newNonce();
  const res = await api.post<{ ticket: string; expires_in: number }>(
    `/conversations/${convId}/tickets`,
    { action, nonce },
  );
  return { "X-Chat-Ticket": res.ticket, "X-Chat-Nonce": nonce };
}
