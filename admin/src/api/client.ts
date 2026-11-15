import type { AuthResponse } from "../types";

const USER_KEY = "whitz_admin_user";
const BASE = "/api";

// Access token stays in memory; the refresh token lives in the HttpOnly cookie.
let accessToken: string | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let lastRefreshAt = 0;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setSession(auth: AuthResponse): void {
  accessToken = auth.access_token;
  lastRefreshAt = Date.now();
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
  scheduleAutoRefresh(auth.expires_in);
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

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const detail = e.detail as { detail?: unknown } | string | null;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
    return e.message;
  }
  return e instanceof Error ? e.message : "请求失败";
}

export function readableError(e: unknown): string {
  return errorMessage(e);
}

let refreshPromise: Promise<boolean> | null = null;

async function callRefresh(): Promise<Response> {
  return fetch(BASE + "/auth/refresh", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

async function doRefresh(): Promise<boolean> {
  try {
    let resp = await callRefresh();
    if (resp.status === 401) {
      // Another tab may have rotated the cookie a moment ago; retry once with the fresh cookie.
      await new Promise((resolve) => setTimeout(resolve, 300));
      resp = await callRefresh();
    }
    if (!resp.ok) return false;
    const auth = (await resp.json()) as AuthResponse;
    if (auth.user.role !== "admin") {
      await revokeSession();
      return false;
    }
    setSession(auth);
    return true;
  } catch {
    return false;
  }
}

function refreshOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

export function tryRefresh(): Promise<boolean> {
  return refreshOnce();
}

if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && accessToken && Date.now() - lastRefreshAt > 5 * 60_000) {
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
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let resp = await fetch(BASE + path, {
    method,
    headers,
    credentials: "include",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  if (resp.status === 401 && !path.startsWith("/auth/")) {
    const ok = await refreshOnce();
    if (ok) {
      const retryHeaders = { ...headers, Authorization: "Bearer " + getAccessToken() };
      resp = await fetch(BASE + path, {
        method,
        headers: retryHeaders,
        credentials: "include",
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: opts.signal,
      });
    }
  }

  if (resp.status === 401) {
    clearSession();
    unauthorizedHandler?.();
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
  try {
    await fetch(BASE + "/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch {
    /* ignore */
  }
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("POST", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("PATCH", path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};

export async function loginRequest(email: string, password: string): Promise<AuthResponse> {
  const auth = await api.post<AuthResponse>("/auth/login", { email, password });
  if (auth.user.role !== "admin") {
    await revokeSession();
    throw new ApiError(403, "该账号没有管理权限");
  }
  return auth;
}
