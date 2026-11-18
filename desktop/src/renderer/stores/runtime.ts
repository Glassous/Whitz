import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { RuntimeProgress, RuntimeStatus, WorkSettings } from "@shared/work-types";
import type { ProviderProtocol } from "@shared/work-types";

function bridge() {
  const api = window.whitzDesktop;
  if (!api) throw new Error("桌面桥接不可用");
  return api;
}

export const useRuntimeStore = defineStore("runtime", () => {
  const status = ref<RuntimeStatus | null>(null);
  const progress = ref<RuntimeProgress | null>(null);
  const settings = ref<WorkSettings | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);

  const ready = computed(() => status.value?.state === "ready");
  const installed = computed(() => Boolean(status.value?.installed));
  const installing = computed(() => status.value?.state === "installing" || progress.value?.phase === "download");

  function apply(result: { status: RuntimeStatus }) {
    status.value = result.status;
  }

  async function init() {
    const api = bridge();
    const result = await api.runtime.status();
    status.value = result.status;
    settings.value = await api.work.settings();
    api.onRuntimeStatus((next) => {
      status.value = next.status;
      if (next.status.state === "ready") progress.value = null;
    });
    api.onRuntimeProgress((next) => {
      progress.value = next;
    });
  }

  async function install() {
    busy.value = true;
    error.value = null;
    try {
      apply(await bridge().runtime.install());
    } catch (err) {
      error.value = err instanceof Error ? err.message : "安装失败";
      throw err;
    } finally {
      busy.value = false;
    }
  }

  async function start() {
    busy.value = true;
    error.value = null;
    try {
      apply(await bridge().runtime.start());
    } catch (err) {
      error.value = err instanceof Error ? err.message : "启动失败";
      throw err;
    } finally {
      busy.value = false;
    }
  }

  async function stop() {
    busy.value = true;
    try {
      apply(await bridge().runtime.stop());
    } finally {
      busy.value = false;
    }
  }

  async function restart() {
    busy.value = true;
    error.value = null;
    try {
      apply(await bridge().runtime.restart());
    } catch (err) {
      error.value = err instanceof Error ? err.message : "重启失败";
      throw err;
    } finally {
      busy.value = false;
    }
  }

  async function loadSettings() {
    settings.value = await bridge().work.settings();
    return settings.value;
  }

  async function saveSettings(patch: {
    protocol?: ProviderProtocol;
    base_url?: string;
    model?: string;
    api_key?: string;
    supports_vision?: boolean;
    approvals?: "smart" | "manual" | "off";
    max_turns?: number;
  }) {
    settings.value = await bridge().work.saveSettings(patch);
    return settings.value;
  }

  async function clearKey() {
    settings.value = await bridge().work.clearKey();
  }

  async function testModel() {
    return bridge().work.testModel();
  }

  return {
    status,
    progress,
    settings,
    busy,
    error,
    ready,
    installed,
    installing,
    init,
    install,
    start,
    stop,
    restart,
    loadSettings,
    saveSettings,
    clearKey,
    testModel,
  };
});
