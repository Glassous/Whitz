import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  api,
  clearSession,
  getAccessToken,
  getUserStorageKey,
  hasStoredSession,
  readStoredUser,
  revokeSession,
  setSession,
  tryRefreshDetail,
} from "../api/client";
import type { AuthResponse, User } from "../types";
import { useConversationsStore } from "./conversations";
import { useChatStore } from "./chat";
import { useCreditsStore } from "./credits";

export type LogoutReason = "manual" | "expired";

export interface LogoutNotice {
  type: LogoutReason;
  message: string;
}

const LOGOUT_NOTICE_KEY = "whitz_logout_notice";

const DEFAULT_NOTICE_MESSAGES: Record<LogoutReason, string> = {
  manual: "你已安全退出登录，如需继续使用请重新登录。",
  expired: "登录状态已过期，请重新登录。",
};

function readStoredNotice(): LogoutNotice | null {
  try {
    const raw = sessionStorage.getItem(LOGOUT_NOTICE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LogoutNotice>;
    if ((parsed.type === "manual" || parsed.type === "expired") && typeof parsed.message === "string") {
      return { type: parsed.type, message: parsed.message };
    }
    return null;
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref<User | null>(readStoredUser());
  const ready = ref(false);
  const logoutNotice = ref<LogoutNotice | null>(readStoredNotice());

  const isAuthenticated = computed(() => !!user.value);
  const isAdmin = computed(() => user.value?.role === "admin");

  function setLogoutNotice(type: LogoutReason, message?: string) {
    const notice: LogoutNotice = {
      type,
      message: message ?? DEFAULT_NOTICE_MESSAGES[type],
    };
    logoutNotice.value = notice;
    try {
      sessionStorage.setItem(LOGOUT_NOTICE_KEY, JSON.stringify(notice));
    } catch {
      /* ignore */
    }
  }

  function clearLogoutNotice() {
    logoutNotice.value = null;
    try {
      sessionStorage.removeItem(LOGOUT_NOTICE_KEY);
    } catch {
      /* ignore */
    }
  }

  function applySession(auth: AuthResponse) {
    clearLogoutNotice();
    setSession(auth);
    user.value = auth.user;
  }

  async function init() {
    if (hasStoredSession()) {
      const res = await tryRefreshDetail();
      if (res === "ok") {
        try {
          const freshUser = await api.get<User>("/users/me");
          user.value = freshUser;
          localStorage.setItem(getUserStorageKey(), JSON.stringify(freshUser));
          clearLogoutNotice();
        } catch {
          if (!getAccessToken()) {
            clearSession();
            user.value = null;
            setLogoutNotice("expired");
          } else {
            user.value = readStoredUser();
          }
        }
      } else if (res === "unauthorized") {
        clearSession();
        user.value = null;
        setLogoutNotice("expired");
      } else {
        // Transient network/server error: keep stored user hint for next reload,
        // but treat current in-memory session as unauthenticated until reachable.
        user.value = null;
      }
    } else {
      user.value = null;
    }
    ready.value = true;
  }

  async function login(identifier: string, password: string) {
    const auth = await api.post<AuthResponse>("/auth/login", { identifier, password });
    applySession(auth);
  }

  async function loginWithCode(email: string, code: string) {
    const auth = await api.post<AuthResponse>("/auth/login/code", { email, code });
    applySession(auth);
  }

  async function register(payload: {
    email: string;
    code: string;
    password: string;
    display_name: string;
  }) {
    const auth = await api.post<AuthResponse>("/auth/register", payload);
    applySession(auth);
  }

  function resetClientStores() {
    useConversationsStore().reset();
    useChatStore().reset();
    useCreditsStore().reset();
  }

  function forceLogout(reason?: LogoutReason) {
    clearSession();
    user.value = null;
    resetClientStores();
    if (reason) setLogoutNotice(reason);
  }

  async function logout() {
    await revokeSession();
    forceLogout("manual");
  }

  async function refreshUser() {
    const freshUser = await api.get<User>("/users/me");
    user.value = freshUser;
    localStorage.setItem(getUserStorageKey(), JSON.stringify(freshUser));
  }

  async function handleStorageSync(e: StorageEvent, callbacks: { onLoggedOut: () => void; onLoggedIn: () => void }) {
    if (e.key !== getUserStorageKey()) return;
    if (!e.newValue && user.value) {
      forceLogout("manual");
      callbacks.onLoggedOut();
    } else if (e.newValue && !user.value) {
      const res = await tryRefreshDetail();
      if (res === "ok") {
        try {
          user.value = await api.get<User>("/users/me");
        } catch {
          user.value = readStoredUser();
        }
        clearLogoutNotice();
        callbacks.onLoggedIn();
      }
    }
  }

  return {
    user,
    ready,
    logoutNotice,
    isAuthenticated,
    isAdmin,
    setLogoutNotice,
    clearLogoutNotice,
    init,
    login,
    loginWithCode,
    register,
    logout,
    forceLogout,
    refreshUser,
    handleStorageSync,
  };
});
