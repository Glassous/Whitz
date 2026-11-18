import type { HostAdapter, HostRefreshResult } from "@web/host";
import type { AuthResponse, User } from "@web/types";

function desktop() {
  const api = window.whitzDesktop;
  if (!api) throw new Error("桌面桥接不可用");
  return api;
}

export function createDesktopHost(apiBase: string): HostAdapter {
  return {
    kind: "desktop",
    transport: { baseUrl: apiBase, credentials: "omit" },
    capabilities: { work: true, localRuntime: true, secureStore: true },
    async refresh(): Promise<HostRefreshResult> {
      try {
        const result = await desktop().auth.refresh();
        if (result.reason === "ok" && result.session) {
          const auth: AuthResponse = {
            access_token: result.session.access_token,
            refresh_token: "",
            token_type: "bearer",
            expires_in: result.session.expires_in,
            user: result.session.user as unknown as User,
          };
          return { reason: "ok", auth };
        }
        return { reason: result.reason, auth: null };
      } catch {
        return { reason: "error", auth: null };
      }
    },
    persistSession(auth: AuthResponse) {
      if (!auth.refresh_token) return;
      void desktop()
        .auth.persist(auth.refresh_token, auth.refresh_expires_in)
        .catch(() => undefined);
    },
    async revokeSession() {
      try {
        await desktop().auth.logout();
      } catch {
        /* ignore */
      }
    },
  };
}
