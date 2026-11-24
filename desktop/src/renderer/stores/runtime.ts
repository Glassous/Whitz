import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type {
  LocalGatewayStatus,
  OpenCodeConfigSavePatch,
  OpenCodeConfigSnapshot,
  OpenCodeModelOption,
  OpenCodeProviderInput,
  RuntimeProgress,
  RuntimeStatus,
  WorkFormatterStatus,
  WorkLspStatus,
  WorkMcpServerInfo,
  WorkMcpServerInput,
  WorkProviderCatalogItem,
  WorkProviderOAuthStart,
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
  const providerCatalog = ref<WorkProviderCatalogItem[]>([]);
  const mcpServers = ref<WorkMcpServerInfo[]>([]);
  const lspStatuses = ref<WorkLspStatus[]>([]);
  const formatterStatuses = ref<WorkFormatterStatus[]>([]);
  const busy = ref(false);
  const upgrading = ref(false);
  const error = ref<string | null>(null);

  const ready = computed(() => status.value?.state === "ready");
  const installed = computed(() => Boolean(status.value?.installed));
  const installing = computed(() => false);
  const gateway = computed<LocalGatewayStatus | null>(() => status.value?.gateway ?? null);

  const allModels = computed<OpenCodeModelOption[]>(() => opencodeConfig.value?.available_models ?? []);
  const enabledModels = computed<OpenCodeModelOption[]>(() => {
    const all = allModels.value;
    const whitelist = settings.value?.model.enabled_models ?? null;
    if (whitelist === null) return all;
    const allowed = new Set(whitelist);
    return all.filter((m) => allowed.has(m.ref));
  });

  function apply(result: { status: RuntimeStatus }) {
    status.value = result.status;
  }

  async function init() {
    const api = bridge();
    const result = await api.runtime.status();
    status.value = result.status;
    settings.value = await api.work.settings();
    opencodeConfig.value = await api.opencode.config().catch(() => null);
    mcpServers.value = opencodeConfig.value?.mcp_servers ?? (await api.opencode.mcpList().catch(() => []));
    api.onRuntimeStatus((next) => {
      status.value = next.status;
      if (next.status.state === "ready") {
        progress.value = null;
        void loadOpenCodeConfig().catch(() => undefined);
      }
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
    if (opencodeConfig.value?.mcp_servers) {
      mcpServers.value = opencodeConfig.value.mcp_servers;
    }
    return opencodeConfig.value;
  }

  async function loadMcpServers(workspacePath?: string | null) {
    mcpServers.value = await bridge().opencode.mcpList(workspacePath);
    return mcpServers.value;
  }

  async function upsertMcpServer(input: WorkMcpServerInput) {
    mcpServers.value = await bridge().opencode.upsertMcp(input);
    await loadOpenCodeConfig().catch(() => undefined);
    return mcpServers.value;
  }

  async function deleteMcpServer(name: string) {
    mcpServers.value = await bridge().opencode.deleteMcp(name);
    await loadOpenCodeConfig().catch(() => undefined);
    return mcpServers.value;
  }

  async function toggleMcpServer(name: string, connect: boolean, workspacePath?: string | null) {
    mcpServers.value = await bridge().opencode.toggleMcp(name, connect, workspacePath);
    return mcpServers.value;
  }

  async function loadLspStatus(workspacePath?: string | null) {
    lspStatuses.value = await bridge().opencode.lspStatus(workspacePath).catch(() => []);
    return lspStatuses.value;
  }

  async function loadFormatterStatus(workspacePath?: string | null) {
    formatterStatuses.value = await bridge().opencode.formatterStatus(workspacePath).catch(() => []);
    return formatterStatuses.value;
  }

  async function authMcpServer(name: string, workspacePath?: string | null) {
    mcpServers.value = await bridge().opencode.authMcp(name, workspacePath);
    return mcpServers.value;
  }

  async function removeMcpAuth(name: string, workspacePath?: string | null) {
    mcpServers.value = await bridge().opencode.removeMcpAuth(name, workspacePath);
    return mcpServers.value;
  }

  async function loadProviderCatalog(workspacePath?: string | null) {
    providerCatalog.value = await bridge().opencode.providerCatalog(workspacePath).catch(() => []);
    return providerCatalog.value;
  }

  async function setProviderApiKey(providerId: string, apiKey: string) {
    opencodeConfig.value = await bridge().opencode.setProviderApiKey(providerId, apiKey);
    await Promise.all([loadSettings().catch(() => undefined), loadProviderCatalog().catch(() => undefined)]);
    return opencodeConfig.value;
  }

  async function startProviderOAuth(
    providerId: string,
    methodIndex: number,
    inputs?: Record<string, string>,
    workspacePath?: string | null,
  ): Promise<WorkProviderOAuthStart> {
    return bridge().opencode.startProviderOAuth(providerId, methodIndex, inputs, workspacePath);
  }

  async function completeProviderOAuth(
    providerId: string,
    methodIndex: number,
    code?: string,
    workspacePath?: string | null,
  ) {
    opencodeConfig.value = await bridge().opencode.completeProviderOAuth(providerId, methodIndex, code, workspacePath);
    await Promise.all([loadSettings().catch(() => undefined), loadProviderCatalog(workspacePath).catch(() => undefined)]);
    return opencodeConfig.value;
  }

  async function upgrade(target?: string) {
    upgrading.value = true;
    error.value = null;
    try {
      const res = await bridge().runtime.upgrade(target);
      apply(await bridge().runtime.status());
      await loadOpenCodeConfig().catch(() => undefined);
      return res;
    } catch (err) {
      error.value = err instanceof Error ? err.message : "升级失败";
      throw err;
    } finally {
      upgrading.value = false;
    }
  }

  async function setEnabledModels(refs: string[] | null) {
    return saveSettings({ enabled_models: refs });
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
    providerCatalog,
    mcpServers,
    lspStatuses,
    formatterStatuses,
    allModels,
    enabledModels,
    busy,
    upgrading,
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
    upgrade,
    loadSettings,
    saveSettings,
    setEnabledModels,
    loadOpenCodeConfig,
    loadProviderCatalog,
    setProviderApiKey,
    startProviderOAuth,
    completeProviderOAuth,
    loadMcpServers,
    upsertMcpServer,
    deleteMcpServer,
    toggleMcpServer,
    authMcpServer,
    removeMcpAuth,
    loadLspStatus,
    loadFormatterStatus,
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
