import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type {
  LocalGatewayStatus,
  OpenCodeConfigSavePatch,
  OpenCodeConfigSnapshot,
  OpenCodeProviderInput,
  RuntimeProgress,
  RuntimeStatus,
  WorkSettings,
  WorkSettingsPatch,
} from "@shared/work-types";

function bridge() {
  const api = window.whitzDesktop;
  if (!api) throw new Error("桌面桥接不可用");
  return api;
}

export const useRuntimeStore = defineStore("runtime", () => {
  const status = ref<RuntimeStatus | null>(null);
  const progress = ref<RuntimeProgress | null>(null);
  const settings = ref<WorkSettings | null>(null);
  const opencodeConfig = ref<OpenCodeConfigSnapshot | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);

  const ready = computed(() => status.value?.state === "ready");
  const installed = computed(() => Boolean(status.value?.installed));
  const installing = computed(() => false);
  const gateway = computed<LocalGatewayStatus | null>(() => status.value?.gateway ?? null);

  function apply(result: { status: RuntimeStatus }) {
    status.value = result.status;
  }

  async function init() {
    const api = bridge();
    const result = await api.runtime.status();
    status.value = result.status;
    settings.value = await api.work.settings();
    opencodeConfig.value = await api.opencode.config().catch(() => null);
    api.onRuntimeStatus((next) => {
      status.value = next.status;
      if (next.status.state === "ready") progress.value = null;
    });
    api.onRuntimeProgress((next) => {
      progress.value = next;
    });
  }

  async function redetect() {
    busy.value = true;
    error.value = null;
    try {
      apply(await bridge().runtime.redetect());
      await loadOpenCodeConfig().catch(() => undefined);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "检测失败";
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
      await loadOpenCodeConfig().catch(() => undefined);
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

  async function saveSettings(patch: WorkSettingsPatch) {
    settings.value = await bridge().work.saveSettings(patch);
    await loadOpenCodeConfig().catch(() => undefined);
    return settings.value;
  }

  async function loadOpenCodeConfig() {
    opencodeConfig.value = await bridge().opencode.config();
    return opencodeConfig.value;
  }

  async function saveOpenCodeConfig(patch: OpenCodeConfigSavePatch) {
    opencodeConfig.value = await bridge().opencode.saveConfig(patch);
    await loadSettings().catch(() => undefined);
    return opencodeConfig.value;
  }

  async function upsertOpenCodeProvider(input: OpenCodeProviderInput) {
    opencodeConfig.value = await bridge().opencode.upsertProvider(input);
    await loadSettings().catch(() => undefined);
    return opencodeConfig.value;
  }

  async function deleteOpenCodeProvider(id: string) {
    opencodeConfig.value = await bridge().opencode.deleteProvider(id);
    await loadSettings().catch(() => undefined);
    return opencodeConfig.value;
  }

  async function writeWhitzToOpenCode() {
    opencodeConfig.value = await bridge().opencode.writeWhitzProvider();
    await loadSettings().catch(() => undefined);
    return opencodeConfig.value;
  }

  async function removeWhitzFromOpenCode() {
    opencodeConfig.value = await bridge().opencode.removeWhitzProvider();
    await loadSettings().catch(() => undefined);
    return opencodeConfig.value;
  }

  async function openOpenCodeConfigDir() {
    await bridge().opencode.openConfigDir();
  }

  async function pickExe(): Promise<string | null> {
    return bridge().runtime.pickExe();
  }

  async function testModel() {
    return bridge().work.testModel();
  }

  return {
    status,
    progress,
    settings,
    opencodeConfig,
    busy,
    error,
    ready,
    installed,
    installing,
    gateway,
    init,
    redetect,
    start,
    stop,
    restart,
    loadSettings,
    saveSettings,
    loadOpenCodeConfig,
    saveOpenCodeConfig,
    upsertOpenCodeProvider,
    deleteOpenCodeProvider,
    writeWhitzToOpenCode,
    removeWhitzFromOpenCode,
    openOpenCodeConfigDir,
    pickExe,
    testModel,
  };
});
