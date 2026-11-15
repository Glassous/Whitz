import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  api,
  clearSession,
  hasStoredSession,
  loginRequest,
  readStoredUser,
  revokeSession,
  setSession,
  tryRefresh,
} from "../api/client";
import type { AuthResponse, User } from "../types";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<User | null>(readStoredUser());
  const ready = ref(false);

  const isAuthenticated = computed(() => !!user.value && user.value.role === "admin");

  function applySession(auth: AuthResponse) {
    setSession(auth);
    user.value = auth.user;
  }

  async function init() {
    if (hasStoredSession()) {
      const refreshed = await tryRefresh();
      if (refreshed) {
        try {
          const me = await api.get<User>("/users/me");
          if (me.role === "admin") {
            user.value = me;
          } else {
            await revokeSession();
            clearSession();
            user.value = null;
          }
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
    const auth = await loginRequest(email, password);
    applySession(auth);
  }

  function forceLogout() {
    clearSession();
    user.value = null;
  }

  async function logout() {
    await revokeSession();
    forceLogout();
  }

  return { user, ready, isAuthenticated, init, login, logout, forceLogout };
});
