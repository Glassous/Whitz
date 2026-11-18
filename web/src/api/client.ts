import { getHost, type RefreshResult } from "../host";
import type { AuthResponse } from "../types";

const USER_KEY = "whitz_user";

export type { RefreshResult };

function baseUrl(): string {
  return getHost().transport.baseUrl;
}

function credentials(): RequestCredentials {
  return getHost().transport.credentials;
}

// The access token stays in memory; the refresh token lives in an HttpOnly cookie.
let accessToken: string | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let lastRefreshAt = 0;

function parseJwtExpMs(token: string): number | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = base64.length % 4 === 0 ? "" : "=".repeat(4 - (base64.length % 4));
    const json = JSON.parse(atob(base64 + pad)) as { exp?: unknown };
    return typeof json.exp === "number" ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

export function isAccessTokenExpiringSoon(bufferMs = 30_000): boolean {
  if (!accessToken) return true;
  const expMs = parseJwtExpMs(accessToken);
  if (expMs === null) return false;
  return Date.now() >= expMs - bufferMs;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getUserStorageKey(): string {
  return USER_KEY;
}

export function setSession(auth: AuthResponse): void {
  applySession(auth, true);
}

function applySession(auth: AuthResponse, persist: boolean): void {
  accessToken = auth.access_token;
  lastRefreshAt = Date.now();
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
  scheduleAutoRefresh(auth.expires_in);
  if (persist) getHost().persistSession(auth);
}

export function updateAccessToken(token: string): void {
  accessToken = token;
}

export function clearSession(): void {
  accessToken = null;
  lastRefreshAt = 0;
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }
  localStorage.removeItem(USER_KEY);
}

export function readStoredUser(): AuthResponse["user"] | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthResponse["user"];
  } catch {
    return null;
  }
}

export function hasStoredSession(): boolean {
  return readStoredUser() !== null;
}

function scheduleAutoRefresh(expiresIn?: number): void {
  if (refreshTimer) clearTimeout(refreshTimer);
  const ttlMs = (expiresIn && expiresIn > 0 ? expiresIn : 15 * 60) * 1000;
  const delay = Math.max(30_000, ttlMs - 60_000);
  refreshTimer = setTimeout(() => {
    void refreshOnce();
  }, delay);
}

let unauthorizedHandler: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  unauthorizedHandler = fn;
}

export function handleUnauthorized(): void {
  clearSession();
  unauthorizedHandler?.();
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function parseBody(resp: Response): Promise<unknown> {
  const text = await resp.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

let refreshPromise: Promise<RefreshResult> | null = null;

async function callRefresh(): Promise<Response> {
  return fetch(baseUrl() + "/auth/refresh", {
    method: "POST",
    credentials: credentials(),
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

async function doRefresh(): Promise<RefreshResult> {
  const host = getHost();
  if (host.kind === "desktop") {
    try {
      const result = await host.refresh();
      if (result.reason === "ok" && result.auth) {
        applySession(result.auth, false);
        return "ok";
      }
      return result.reason;
    } catch {
      return "error";
    }
  }
  try {
    let resp = await callRefresh();
    if (resp.status === 401) {
      // Another tab may have rotated the cookie a moment ago; retry once with the fresh cookie.
      await new Promise((resolve) => setTimeout(resolve, 300));
      resp = await callRefresh();
    }
    if (resp.status === 401 || resp.status === 403) return "unauthorized";
    if (!resp.ok) return "error";
    const auth = (await resp.json()) as AuthResponse;
    applySession(auth, false);
    return "ok";
  } catch {
    return "error";
  }
}

function refreshOnce(): Promise<RefreshResult> {
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export function tryRefreshDetail(): Promise<RefreshResult> {
  return refreshOnce();
}

export async function tryRefresh(): Promise<boolean> {
  return (await refreshOnce()) === "ok";
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (
      document.visibilityState === "visible" &&
      accessToken &&
      (isAccessTokenExpiringSoon(90_000) || Date.now() - lastRefreshAt > 5 * 60_000)
    ) {
      void refreshOnce();
    }
  });
}

export interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
  raw?: boolean;
  headers?: Record<string, string>;
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const isAuthPath = path.startsWith("/auth/");
  if (!isAuthPath && (accessToken || hasStoredSession()) && isAccessTokenExpiringSoon()) {
    await refreshOnce();
  }

  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let resp = await fetch(baseUrl() + path, {
    method,
    headers,
    credentials: credentials(),
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  if (resp.status === 401 && !isAuthPath) {
    const res = await refreshOnce();
    if (res === "ok") {
      const retryHeaders = { ...headers, Authorization: "Bearer " + getAccessToken() };
      resp = await fetch(baseUrl() + path, {
        method,
        headers: retryHeaders,
        credentials: credentials(),
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: opts.signal,
      });
    }
  }

  if (resp.status === 401 && !isAuthPath) {
    handleUnauthorized();
    throw new ApiError(401, "登录已过期，请重新登录");
  }

  if (!resp.ok) {
    throw new ApiError(resp.status, await parseBody(resp));
  }

  if (opts.raw) return resp as unknown as T;
  if (resp.status === 204) return undefined as unknown as T;
  return (await parseBody(resp)) as T;
}

export async function revokeSession(): Promise<void> {
  await getHost().revokeSession();
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("POST", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("PATCH", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("PUT", path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};
