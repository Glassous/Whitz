import type { AuthResponse } from "../types";

export type RefreshResult = "ok" | "unauthorized" | "error";

export interface HostTransport {
  baseUrl: string;
  credentials: RequestCredentials;
}

export interface HostCapabilities {
  work: boolean;
  localRuntime: boolean;
  secureStore: boolean;
}

export interface HostRefreshResult {
  reason: RefreshResult;
  auth: AuthResponse | null;
}

export interface HostAdapter {
  kind: "web" | "desktop";
  transport: HostTransport;
  capabilities: HostCapabilities;
  /** Performs a token refresh. Desktop delegates to the main process. */
  refresh(): Promise<HostRefreshResult>;
  /** Persists the refresh token (desktop only; web relies on the HttpOnly cookie). */
  persistSession(auth: AuthResponse): void;
  /** Revokes the current session. Desktop clears the OS credential store. */
  revokeSession(): Promise<void>;
}

const webTransport: HostTransport = { baseUrl: "/api", credentials: "include" };

const webHost: HostAdapter = {
  kind: "web",
  transport: webTransport,
  capabilities: { work: false, localRuntime: false, secureStore: false },
  async refresh() {
    return { reason: "error", auth: null };
  },
  persistSession() {
    /* cookie based */
  },
  async revokeSession() {
    try {
      await fetch(webTransport.baseUrl + "/auth/logout", {
        method: "POST",
        credentials: webTransport.credentials,
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } catch {
      /* ignore */
    }
  },
};

let active: HostAdapter = webHost;

export function setHost(host: HostAdapter): void {
  active = host;
}

export function getHost(): HostAdapter {
  return active;
}

export function isDesktopHost(): boolean {
  return active.kind === "desktop";
}
