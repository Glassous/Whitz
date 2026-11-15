import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  api,
  clearSession,
  hasStoredSession,
  readStoredUser,
  revokeSession,
  setSession,
  tryRefresh,
} from "../api/client";
import type { AuthResponse, SecurityQuestionInput, User } from "../types";
import { useConversationsStore } from "./conversations";
import { useChatStore } from "./chat";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<User | null>(readStoredUser());
  const ready = ref(false);

  const isAuthenticated = computed(() => !!user.value);
  const isAdmin = computed(() => user.value?.role === "admin");

  function applySession(auth: AuthResponse) {
    setSession(auth);
    user.value = auth.user;
  }

  async function init() {
    if (hasStoredSession()) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        try {
          user.value = await api.get<User>("/users/me");
        } catch {
          clearSession();
          user.value = null;
        }
      } else {
        clearSession();
        user.value = null;
      }
    }
    ready.value = true;
  }

  async function login(email: string, password: string) {
    const auth = await api.post<AuthResponse>("/auth/login", { email, password });
    applySession(auth);
  }

  async function register(payload: {
    email: string;
    password: string;
    display_name: string;
    security_questions: SecurityQuestionInput[];
  }) {
    const auth = await api.post<AuthResponse>("/auth/register", payload);
    applySession(auth);
  }

  function forceLogout() {
    clearSession();
    user.value = null;
    useConversationsStore().reset();
    useChatStore().reset();
  }

  async function logout() {
    await revokeSession();
    forceLogout();
  }

  async function refreshUser() {
    user.value = await api.get<User>("/users/me");
  }

  return { user, ready, isAuthenticated, isAdmin, init, login, register, logout, forceLogout, refreshUser };
});
