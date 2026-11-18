import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { PolicyView } from "@shared/ipc-contract";
import type { ConnectivityState, DesktopInfo, DesktopSession } from "@shared/work-types";

function bridge() {
  const api = window.whitzDesktop;
  if (!api) throw new Error("桌面桥接不可用");
  return api;
}

export const useDesktopStore = defineStore("desktop", () => {
  const info = ref<DesktopInfo | null>(null);
  const session = ref<DesktopSession | null>(null);
  const policy = ref<PolicyView | null>(null);
  const connectivity = ref<ConnectivityState>({
    online: true,
    checked_at: "",
    latency_ms: null,
    forced_offline: false,
  });
  const ready = ref(false);

  const loggedIn = computed(() => Boolean(session.value));
  const online = computed(() => connectivity.value.online && !connectivity.value.forced_offline);
  const workEnabled = computed(() => policy.value?.enabled ?? false);
  const user = computed(() => session.value?.user ?? null);

  async function init() {
    const api = bridge();
    info.value = await api.info();
    connectivity.value = await api.net.get();
    policy.value = await api.policy.get();
    session.value = await api.auth.session();
    ready.value = true;

    api.onAuthChanged((next) => {
      session.value = next;
    });
    api.onConnectivity((next) => {
      connectivity.value = next;
    });
    api.onPolicyChanged((next) => {
      policy.value = next;
    });
  }

  async function refreshPolicy() {
    policy.value = await bridge().policy.refresh();
  }

  async function refreshConnectivity() {
    connectivity.value = await bridge().net.check();
  }

  async function setForcedOffline(value: boolean) {
    connectivity.value = await bridge().net.forceOffline(value);
  }

  async function loginWithPassword(email: string, password: string) {
    session.value = await bridge().auth.loginPassword(email, password);
  }

  async function loginWithCode(email: string, code: string) {
    session.value = await bridge().auth.loginCode(email, code);
  }

  async function register(email: string, password: string, displayName: string, code: string) {
    session.value = await bridge().auth.register(email, password, displayName, code);
  }

  async function logout() {
    await bridge().auth.logout();
    session.value = null;
  }

  return {
    info,
    session,
    policy,
    connectivity,
    ready,
    loggedIn,
    online,
    workEnabled,
    user,
    init,
    refreshPolicy,
    refreshConnectivity,
    setForcedOffline,
    loginWithPassword,
    loginWithCode,
    register,
    logout,
  };
});
