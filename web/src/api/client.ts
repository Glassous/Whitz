import type { AuthResponse } from "../types";

const ACCESS_KEY = "whitz_access";
const REFRESH_KEY = "whitz_refresh";
const USER_KEY = "whitz_user";

const BASE = "/api";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

export function setSession(auth: AuthResponse): void {
  localStorage.setItem(ACCESS_KEY, auth.access_token);
  localStorage.setItem(REFRESH_KEY, auth.refresh_token);
  localStorage.setItem(USER_KEY, JSON.stringify(auth.user));
}

export function updateAccessToken(token: string): void {
  localStorage.setItem(ACCESS_KEY, token);
}

export function clearSession(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
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

let refreshPromise: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;
  try {
    const resp = await fetch(BASE + "/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!resp.ok) return false;
    const auth = (await resp.json()) as AuthResponse;
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

export interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
  raw?: boolean;
}

export async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const token = getAccessToken();
  if (token) headers["Authorization"] = "Bearer " + token;

  let resp = await fetch(BASE + path, {
    method,
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  if (resp.status === 401 && getRefreshToken()) {
    const ok = await refreshOnce();
    if (ok) {
      const retryHeaders = { ...headers, Authorization: "Bearer " + getAccessToken() };
      resp = await fetch(BASE + path, {
        method,
        headers: retryHeaders,
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

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("POST", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("PATCH", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>("PUT", path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};