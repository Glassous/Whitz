import { EventEmitter } from "node:events";
import { ApiError, apiRequest } from "../api";
import { scoped } from "../logger";
import { clearSecrets, readSecrets, writeSecrets } from "../secureStore";
import type { DesktopSession, DesktopUser } from "../../shared/work-types";

const logger = scoped("auth");

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_in: number;
  user: DesktopUser;
}

export const authEvents = new EventEmitter();

let accessToken: string | null = null;
let accessTokenExpiresAt = 0;

function toSession(resp: TokenResponse): DesktopSession {
  accessToken = resp.access_token;
  accessTokenExpiresAt = Date.now() + Math.max(30, resp.expires_in) * 1000;
  return { user: resp.user, access_token: resp.access_token, expires_in: resp.expires_in };
}

function storeRefresh(resp: TokenResponse): void {
  writeSecrets({
    refresh_token: resp.refresh_token,
    refresh_expires_in: resp.refresh_expires_in,
    last_user: resp.user as unknown as Record<string, unknown>,
  });
}

function emit(session: DesktopSession | null): void {
  authEvents.emit("changed", session);
}

async function login(path: string, body: unknown): Promise<DesktopSession> {
  const resp = await apiRequest<TokenResponse>(path, { method: "POST", body });
  storeRefresh(resp);
  accessToken = null;
  const session = toSession(resp);
  emit(session);
  return session;
}

export async function loginPassword(email: string, password: string): Promise<DesktopSession> {
  return login("/auth/login", { email, password });
}

export async function loginCode(email: string, code: string): Promise<DesktopSession> {
  return login("/auth/login/code", { email, code });
}

export async function register(email: string, password: string, displayName: string, code: string): Promise<DesktopSession> {
  return login("/auth/register", { email, password, display_name: displayName, code });
}

export async function sendCode(email: string, purpose: "login" | "register" | "reset") {
  return apiRequest<{ message: string; expires_in: number; cooldown: number }>("/auth/email-code", {
    method: "POST",
    body: { email, purpose },
  });
}

export async function resetPassword(email: string, code: string, password: string): Promise<void> {
  await apiRequest("/auth/reset-password", {
    method: "POST",
    body: { email, code, new_password: password },
  });
}

export async function persistRefreshToken(token: string, refreshExpiresIn?: number): Promise<void> {
  if (!token) return;
  writeSecrets({ refresh_token: token, refresh_expires_in: refreshExpiresIn });
}

export async function refreshSession(): Promise<{ session: DesktopSession | null; reason: "ok" | "unauthorized" | "error" }> {
  const secrets = readSecrets();
  if (!secrets.refresh_token) return { session: null, reason: "unauthorized" };
  try {
    const resp = await apiRequest<TokenResponse>("/auth/refresh", {
      method: "POST",
      body: { refresh_token: secrets.refresh_token },
    });
    storeRefresh(resp);
    const session = toSession(resp);
    emit(session);
    return { session, reason: "ok" };
  } catch (err) {
    if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
      clearSecrets(["refresh_token", "refresh_expires_in"]);
      emit(null);
      return { session: null, reason: "unauthorized" };
    }
    logger.warn("refresh failed", err);
    return { session: null, reason: "error" };
  }
}

export async function currentSession(): Promise<DesktopSession | null> {
  const secrets = readSecrets();
  if (!secrets.refresh_token) return null;
  if (accessToken && Date.now() < accessTokenExpiresAt - 60_000) {
    return {
      user: (secrets.last_user as unknown as DesktopUser) ?? ({
        id: "",
        email: "",
        display_name: "Whitz 用户",
      } as DesktopUser),
      access_token: accessToken,
      expires_in: Math.floor((accessTokenExpiresAt - Date.now()) / 1000),
    };
  }
  const { session } = await refreshSession();
  return session;
}

export async function ensureAccessToken(): Promise<string | null> {
  if (accessToken && Date.now() < accessTokenExpiresAt - 60_000) return accessToken;
  const { session } = await refreshSession();
  return session?.access_token ?? null;
}

export function peekAccessToken(): string | null {
  return accessToken && Date.now() < accessTokenExpiresAt ? accessToken : null;
}

export async function logout(): Promise<void> {
  const secrets = readSecrets();
  if (secrets.refresh_token) {
    await apiRequest("/auth/logout", {
      method: "POST",
      body: { refresh_token: secrets.refresh_token },
    }).catch(() => undefined);
  }
  accessToken = null;
  accessTokenExpiresAt = 0;
  clearSecrets(["refresh_token", "refresh_expires_in"]);
  emit(null);
}
