<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { clearChromeBack, setChromeBack } from "@web/host/chrome";
import { useCreditsStore } from "@web/stores/credits";
import { useTheme, type ThemePreference } from "@web/lib/theme";
import type { OpenCodeModelOption, OpenCodePermissionPreset, WorkAccessMode } from "@shared/work-types";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkStore } from "../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";
import ProviderManagerPanel from "../components/work/ProviderManagerPanel.vue";
import McpManagerPanel from "../components/work/McpManagerPanel.vue";
import FullCommandConfirmModal from "../components/work/FullCommandConfirmModal.vue";

type WorkTab = "models" | "instructions" | "workspace" | "runtime";
type SecondaryPage = "providers" | "mcp" | "raw-config" | null;

const VALID_TABS: readonly WorkTab[] = ["models", "instructions", "workspace", "runtime"];
const VALID_SUBS: readonly Exclude<SecondaryPage, null>[] = ["providers", "mcp", "raw-config"];

const route = useRoute();
const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();
const credits = useCreditsStore();
const { preference, set: setTheme } = useTheme();

const themeOptions: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

const navItems: Array<{ key: WorkTab; label: string; desc: string }> = [
  { key: "models", label: "模型与接入", desc: "接入方式、启用模型清单与额度" },
  { key: "instructions", label: "权限、MCP 与指令", desc: "审批策略、AGENTS.md 与 MCP 扩展" },
  { key: "workspace", label: "项目与技能", desc: "已保存项目目录与本机技能" },
  { key: "runtime", label: "运行时与账号", desc: "OpenCode 服务状态、账号与策略" },
];

function initialTab(): WorkTab {
  const raw = Array.isArray(route.query.tab) ? route.query.tab[0] : route.query.tab;
  return typeof raw === "string" && (VALID_TABS as readonly string[]).includes(raw) ? (raw as WorkTab) : "models";
}

function initialSub(): SecondaryPage {
  const raw = Array.isArray(route.query.sub) ? route.query.sub[0] : route.query.sub;
  return typeof raw === "string" && (VALID_SUBS as readonly string[]).includes(raw) ? (raw as Exclude<SecondaryPage, null>) : null;
}

const activeTab = ref<WorkTab>(initialTab());
const subPage = ref<SecondaryPage>(initialSub());
const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;
let chromeBackToken: number | null = null;

// Models & Gateway state
const modelFilter = ref("");
const mode = ref<WorkAccessMode>("opencode_local");
const defaultModel = ref("");
const smallModel = ref("");
const savingMode = ref(false);
const copiedGateway = ref(false);
const testing = ref(false);
const testResult = ref<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null } | null>(null);
const modelsMsg = ref<string | null>(null);
const modelsErr = ref<string | null>(null);

// Permissions, Instructions & Raw JSON
const permissionPreset = ref<Exclude<OpenCodePermissionPreset, "custom">>("smart");
const fullCommandConfirmOpen = ref(false);
const fullCommandMode = computed(() => Boolean(runtime.settings?.model.full_command_mode));

function toggleFullCommandFromSettings() {
  if (fullCommandMode.value) {
    void runtime.saveSettings({ full_command_mode: false });
    return;
  }
  fullCommandConfirmOpen.value = true;
}

async function confirmFullCommandFromSettings() {
  fullCommandConfirmOpen.value = false;
  await runtime.saveSettings({ full_command_mode: true });
}
const agentsMd = ref("");
const rawJson = ref("");
const rawJsonError = ref<string | null>(null);
const savingInstructions = ref(false);
const instructionsMsg = ref<string | null>(null);

// Runtime exe
const customExe = ref("");
const savingRuntime = ref(false);
const runtimeMsg = ref<string | null>(null);

const cfg = computed(() => runtime.opencodeConfig);
const gatewayUrl = computed(() => runtime.gateway?.base_url ?? cfg.value?.whitz_base_url ?? "启动中…");

const enabledSet = computed<Set<string> | null>(() => {
  const list = runtime.settings?.model.enabled_models ?? null;
  return list === null ? null : new Set(list);
});

const enabledCount = computed(() => {
  const all = runtime.allModels;
  if (!enabledSet.value) return all.length;
  return all.filter((m) => enabledSet.value!.has(m.ref)).length;
});

const groupedAllModels = computed(() => {
  const q = modelFilter.value.trim().toLowerCase();
  const map = new Map<string, { providerID: string; items: OpenCodeModelOption[] }>();
  for (const m of runtime.allModels) {
    if (q && !m.ref.toLowerCase().includes(q) && !m.label.toLowerCase().includes(q)) continue;
    let bucket = map.get(m.providerID);
    if (!bucket) {
      bucket = { providerID: m.providerID, items: [] };
      map.set(m.providerID, bucket);
    }
    bucket.items.push(m);
  }
  return Array.from(map.values());
});

const secondaryTitle = computed(() => {
  if (subPage.value === "providers") return "Provider 与自定义模型管理";
  if (subPage.value === "mcp") return "MCP 服务器管理";
  if (subPage.value === "raw-config") return "原始配置 (opencode.json)";
  return "";
});

const sourceLabel = computed(() => {
  const s = runtime.status?.source;
  if (s === "custom") return "用户指定路径";
  if (s === "npm") return "本机 npm (opencode-ai)";
  if (s === "scoop") return "本机 Scoop";
  if (s === "winget") return "本机 WinGet";
  if (s === "system") return "本机 PATH 环境";
  return "未检测到";
});

function isModelEnabled(refStr: string): boolean {
  if (!enabledSet.value) return true;
  return enabledSet.value.has(refStr);
}

async function toggleModelEnabled(refStr: string) {
  const allRefs = runtime.allModels.map((m) => m.ref);
  const current = new Set(enabledSet.value ?? allRefs);
  if (current.has(refStr)) current.delete(refStr);
  else current.add(refStr);
  await runtime.setEnabledModels(Array.from(current));
}

async function enableAllModels() {
  await runtime.setEnabledModels(null);
}

async function setDefaultComposerModel(refStr: string) {
  await runtime.saveSettings({ default_composer_model: refStr });
  defaultModel.value = refStr;
  if (!isModelEnabled(refStr)) {
    await toggleModelEnabled(refStr);
  }
  modelsMsg.value = `已将「${refStr}」设为默认模型`;
}

async function switchMode(nextMode: WorkAccessMode) {
  if (nextMode === "builtin" && !desktop.loggedIn) return;
  mode.value = nextMode;
  savingMode.value = true;
  modelsMsg.value = null;
  modelsErr.value = null;
  try {
    await runtime.saveSettings({ mode: nextMode });
    modelsMsg.value = nextMode === "builtin" ? "已切换为 Whitz 内置（共享额度）" : "已切换为接入本机 OpenCode 配置";
  } catch (err) {
    modelsErr.value = err instanceof Error ? err.message : "切换失败";
  } finally {
    savingMode.value = false;
  }
}

async function writeWhitzToConfig() {
  savingMode.value = true;
  try {
    await runtime.writeWhitzToOpenCode();
    modelsMsg.value = "已写入本机 opencode.json";
  } catch (err) {
    modelsErr.value = err instanceof Error ? err.message : "写入失败";
  } finally {
    savingMode.value = false;
  }
}

async function removeWhitzFromConfig() {
  savingMode.value = true;
  try {
    await runtime.removeWhitzFromOpenCode();
    modelsMsg.value = "已从 opencode.json 移除 Whitz";
  } catch (err) {
    modelsErr.value = err instanceof Error ? err.message : "移除失败";
  } finally {
    savingMode.value = false;
  }
}

async function copyGatewayUrl() {
  if (!runtime.gateway?.base_url) return;
  await navigator.clipboard.writeText(runtime.gateway.base_url).catch(() => undefined);
  copiedGateway.value = true;
  setTimeout(() => {
    copiedGateway.value = false;
  }, 1800);
}

async function runModelTest() {
  testing.value = true;
  testResult.value = null;
  try {
    testResult.value = await runtime.testModel();
  } catch (err) {
    testResult.value = { ok: false, latency_ms: null, model: null, detail: err instanceof Error ? err.message : "测试失败" };
  } finally {
    testing.value = false;
  }
}

async function saveInstructionsAndPerms() {
  savingInstructions.value = true;
  instructionsMsg.value = null;
  try {
    await runtime.saveOpenCodeConfig({
      default_model: defaultModel.value.trim(),
      small_model: smallModel.value.trim(),
      permission_preset: permissionPreset.value,
      agents_md: agentsMd.value,
    });
    instructionsMsg.value = "已同步保存权限与全局指令 (AGENTS.md)";
  } catch (err) {
    rawJsonError.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    savingInstructions.value = false;
  }
}

async function saveRawJsonConfig() {
  savingRuntime.value = true;
  rawJsonError.value = null;
  runtimeMsg.value = null;
  try {
    await runtime.saveOpenCodeConfig({ raw_json: rawJson.value });
    runtimeMsg.value = "已写入并同步本机 opencode.json";
  } catch (err) {
    rawJsonError.value = err instanceof Error ? err.message : "JSON 校验或写入失败";
  } finally {
    savingRuntime.value = false;
  }
}

async function pickCustomExe() {
  const picked = await runtime.pickExe();
  if (picked) {
    customExe.value = picked;
    await runtime.saveSettings({ custom_opencode_exe: picked });
    await runtime.redetect().catch(() => undefined);
  }
}

async function saveCustomExe() {
  savingRuntime.value = true;
  runtimeMsg.value = null;
  try {
    await runtime.saveSettings({ custom_opencode_exe: customExe.value.trim() });
    await runtime.redetect().catch(() => undefined);
    runtimeMsg.value = "已保存可执行路径";
  } finally {
    savingRuntime.value = false;
  }
}

function openLogs() {
  void window.whitzDesktop?.runtime.openLogs();
}

function openSubPage(page: Exclude<SecondaryPage, null>) {
  subPage.value = page;
}

function goBackFromSub() {
  if (subPage.value === "providers") activeTab.value = "models";
  else if (subPage.value === "mcp" || subPage.value === "raw-config") activeTab.value = "instructions";
  subPage.value = null;
}

function selectTab(tab: WorkTab) {
  subPage.value = null;
  activeTab.value = tab;
}

function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
}

watch(
  () => runtime.settings,
  (s) => {
    if (!s) return;
    mode.value = s.model.mode;
    customExe.value = s.model.custom_opencode_exe ?? "";
  },
  { immediate: true, deep: true },
);

watch(
  () => runtime.opencodeConfig,
  (c) => {
    if (!c) return;
    defaultModel.value = c.default_model;
    smallModel.value = c.small_model;
    permissionPreset.value = c.permission_preset === "custom" ? "smart" : c.permission_preset;
    agentsMd.value = c.agents_md;
    rawJson.value = c.raw_json;
  },
  { immediate: true, deep: true },
);

watch(
  () => subPage.value,
  (sub) => {
    if (sub) {
      chromeBackToken = setChromeBack({ label: "返回 Work 设置", run: goBackFromSub });
    } else {
      chromeBackToken = setChromeBack({ label: "返回工作台", run: () => void router.push({ name: "work" }) });
    }
  },
  { immediate: true },
);

onMounted(() => {
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  void runtime.loadSettings();
  void runtime.loadOpenCodeConfig().catch(() => undefined);
  void runtime.loadMcpServers(work.activeWorkspace?.path).catch(() => undefined);
  void desktop.refreshPolicy();
  void work.loadWorkspaceState();
  void work.loadSkills();
  if (desktop.loggedIn) void credits.fetch().catch(() => undefined);
});

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener("change", onMediaChange);
  if (chromeBackToken !== null) clearChromeBack(chromeBackToken);
});
</script>

<template>
  <div class="flex h-full w-full overflow-hidden bg-canvas text-fg">
    <!-- Left Navigation Sidebar (Hidden when viewing Secondary Subpage, matching Web SettingsView.vue) -->
    <aside
      v-if="!subPage"
      aria-label="Work 设置导航"
      class="hidden w-[290px] shrink-0 flex-col bg-sidebar p-4 md:flex lg:w-[310px]"
    >
      <!-- Theme Switcher (Identical to Web SettingsView.vue) -->
      <fieldset class="m-0 mb-5 border-0 p-0">
        <legend class="visually-hidden">外观主题</legend>
        <div class="grid grid-cols-3 gap-1 rounded-xl bg-surface p-1 dark:bg-canvas">
          <label
            v-for="opt in themeOptions"
            :key="opt.value"
            class="flex h-8.5 cursor-pointer items-center justify-center rounded-lg px-2 text-[12.5px] transition-all"
            :class="preference === opt.value ? 'bg-canvas font-medium text-fg shadow-xs dark:bg-active' : 'text-fg-muted hover:text-fg'"
          >
            <input
              type="radio"
              name="work_theme_preference"
              class="visually-hidden"
              :value="opt.value"
              :checked="preference === opt.value"
              @change="setTheme(opt.value, 'top-left')"
            />
            <span>{{ opt.label }}</span>
          </label>
        </div>
      </fieldset>

      <div class="mb-3 px-2">
        <h1 class="text-[18px] font-semibold tracking-tight text-fg">Work 设置</h1>
        <p class="mt-0.5 text-[12px] text-fg-faint">管理本机 OpenCode 模型、MCP 与工作台行为</p>
      </div>

      <nav class="flex-1 space-y-1 overflow-y-auto custom-scrollbar">
        <button
          v-for="tab in navItems"
          :key="tab.key"
          type="button"
          class="focus-ring flex w-full flex-col rounded-2xl px-3.5 py-2.5 text-left transition-colors"
          :class="activeTab === tab.key ? 'bg-hover/90 text-fg dark:bg-active' : 'text-fg-muted hover:bg-hover/65 hover:text-fg'"
          @click="selectTab(tab.key)"
        >
          <span class="text-[14px] font-medium">{{ tab.label }}</span>
          <span class="mt-0.5 truncate text-[11.5px] text-fg-faint">{{ tab.desc }}</span>
        </button>
      </nav>

      <div class="mt-4 rounded-2xl bg-surface/65 p-3.5 text-[12px] text-fg-faint">
        <p class="font-medium text-fg-muted">需要修改云端 Chat 设置？</p>
        <button
          type="button"
          class="mt-1 text-[12px] text-accent transition-opacity hover:opacity-80"
          @click="router.push({ name: 'settings' })"
        >
          前往 Chat 设置页 →
        </button>
      </div>
    </aside>

    <!-- Main Content Column -->
    <div class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <!-- Mobile Tab Strip (when not in secondary page) -->
      <div v-if="!subPage && !isDesktop" class="flex gap-1.5 overflow-x-auto bg-sidebar/70 px-4 py-2.5">
        <button
          v-for="tab in navItems"
          :key="tab.key"
          type="button"
          class="shrink-0 rounded-full px-3 py-1 text-[12.5px] font-medium transition-colors"
          :class="activeTab === tab.key ? 'bg-active text-fg' : 'text-fg-muted'"
          @click="selectTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Secondary Subpage Top Bar -->
      <header v-if="subPage" class="shrink-0 bg-canvas px-6 pt-5 pb-2 sm:px-8">
        <div class="mx-auto flex max-w-[780px] items-center justify-between gap-3">
          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="goBackFromSub"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
            </svg>
            <span>返回</span>
          </button>
          <h1 class="text-[16px] font-semibold text-fg">{{ secondaryTitle }}</h1>
          <div class="w-14" />
        </div>
      </header>

      <div class="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
        <div class="mx-auto max-w-[780px] space-y-5 px-6 py-7 sm:px-8">
          <!-- SECONDARY SUBPAGE 1: Provider & Custom Model Manager -->
          <ProviderManagerPanel v-if="subPage === 'providers'" />

          <!-- SECONDARY SUBPAGE 2: MCP Manager -->
          <McpManagerPanel v-else-if="subPage === 'mcp'" />

          <!-- SECONDARY SUBPAGE 3: Raw opencode.json Editor -->
          <section v-else-if="subPage === 'raw-config'" class="space-y-4 rounded-2xl bg-surface/65 p-5">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 class="text-[15px] font-semibold text-fg">原始 opencode.json 配置</h2>
                <p class="mt-0.5 font-mono text-[11.5px] text-fg-faint">{{ cfg?.config_file }}</p>
              </div>
              <BaseButton size="sm" variant="secondary" @click="runtime.openOpenCodeConfigDir()">打开配置目录</BaseButton>
            </div>
            <textarea
              v-model="rawJson"
              rows="18"
              spellcheck="false"
              class="focus-ring w-full rounded-2xl bg-code px-4 py-3 font-mono text-[12px] leading-relaxed text-[#e6e5e0] outline-none"
            />
            <p v-if="rawJsonError" class="text-[12.5px] text-danger">{{ rawJsonError }}</p>
            <div class="flex items-center gap-3">
              <BaseButton size="sm" :loading="savingRuntime" @click="saveRawJsonConfig">保存并重载 OpenCode</BaseButton>
              <span v-if="runtimeMsg" class="text-[12.5px]" style="color: var(--success)">{{ runtimeMsg }}</span>
            </div>
          </section>

          <!-- PRIMARY TAB 1: Models, Mode & Enabled Whitelist -->
          <template v-else-if="activeTab === 'models'">
            <!-- Mode & Credits Summary -->
            <section class="rounded-2xl bg-surface/65 p-5 space-y-4">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 class="text-[16px] font-semibold text-fg">默认接入方式</h2>
                  <p class="mt-0.5 text-[12.5px] text-fg-muted">
                    可在下方开启多个模型并在 Work 输入框随时按对话切换；只有选择 <code class="rounded bg-canvas px-1 font-mono text-[11px]">whitz/*</code> 才计入账号共享额度。
                  </p>
                </div>
                <BaseButton size="sm" variant="secondary" :loading="testing" @click="runModelTest">测试通道</BaseButton>
              </div>

              <div class="grid gap-2.5 sm:grid-cols-2">
                <button
                  type="button"
                  class="focus-ring rounded-2xl p-3.5 text-left transition-colors"
                  :class="mode === 'opencode_local' ? 'bg-canvas ring-2 ring-[color:var(--work-accent)]' : 'bg-canvas/55 hover:bg-canvas'"
                  :disabled="savingMode"
                  @click="switchMode('opencode_local')"
                >
                  <p class="text-[13.5px] font-semibold text-fg">接入本机 OpenCode</p>
                  <p class="mt-1 text-[11.5px] text-fg-faint">直接使用本地配置的所有 Provider 与密钥</p>
                </button>
                <button
                  type="button"
                  class="focus-ring rounded-2xl p-3.5 text-left transition-colors disabled:opacity-50"
                  :class="mode === 'builtin' ? 'bg-canvas ring-2 ring-[color:var(--work-accent)]' : 'bg-canvas/55 hover:bg-canvas'"
                  :disabled="savingMode || !desktop.loggedIn"
                  @click="switchMode('builtin')"
                >
                  <p class="text-[13.5px] font-semibold text-fg">Whitz 内置（共享额度）</p>
                  <p class="mt-1 text-[11.5px] text-fg-faint">通过本机 OpenAI 网关调用，与 Chat 共享账号额度</p>
                </button>
              </div>

              <!-- Compact Shared Credits & Localhost Gateway Strip -->
              <div class="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-canvas/75 px-3.5 py-2.5 text-[12px]">
                <div class="min-w-0 flex-1 space-y-0.5">
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-fg">本机网关：</span>
                    <code class="truncate font-mono text-[11.5px] text-fg-muted">{{ gatewayUrl }}</code>
                    <button type="button" class="shrink-0 text-accent hover:underline" @click="copyGatewayUrl">
                      {{ copiedGateway ? "已复制" : "复制" }}
                    </button>
                  </div>
                  <p v-if="desktop.loggedIn && credits.status" class="text-[11px] text-fg-faint">
                    {{ credits.tierLabel }} 额度：本周剩余 {{ credits.status.weekly.limit ? `${credits.weeklyPercent}%` : "不限" }}
                    <template v-if="credits.tier !== 'pro'"> · 5小时剩余 {{ credits.fiveHourPercent }}%</template>
                  </p>
                </div>

                <BaseButton
                  v-if="!cfg?.whitz_configured"
                  size="sm"
                  variant="secondary"
                  :loading="savingMode"
                  @click="writeWhitzToConfig"
                >
                  写入 opencode.json
                </BaseButton>
                <BaseButton
                  v-else
                  size="sm"
                  variant="ghost"
                  :loading="savingMode"
                  @click="removeWhitzFromConfig"
                >
                  移除内置写入
                </BaseButton>
              </div>

              <div v-if="testResult" class="rounded-xl bg-canvas px-3.5 py-2 text-[12px]">
                <span :style="{ color: testResult.ok ? 'var(--success)' : 'var(--danger)' }">
                  {{ testResult.ok ? `连通正常 · ${testResult.model ?? ""} · ${testResult.latency_ms}ms` : "测试失败" }}
                </span>
                <p v-if="testResult.detail" class="mt-0.5 text-fg-muted">{{ testResult.detail }}</p>
              </div>
              <p v-if="modelsMsg" class="text-[12px]" style="color: var(--success)">{{ modelsMsg }}</p>
              <p v-if="modelsErr" class="text-[12px] text-danger">{{ modelsErr }}</p>
            </section>

            <!-- Secondary Page Link: Provider & Custom Model Manager -->
            <button
              type="button"
              class="focus-ring flex w-full items-center justify-between rounded-2xl bg-surface/65 p-4 text-left transition-colors hover:bg-surface"
              @click="openSubPage('providers')"
            >
              <div>
                <p class="text-[14.5px] font-semibold text-fg">管理 Provider 与自定义模型</p>
                <p class="mt-0.5 text-[12px] text-fg-muted">
                  已发现 {{ cfg?.providers.length ?? 0 }} 个服务商 · 新增 OpenAI / Anthropic / DeepSeek / 自定义兼容接口
                </p>
              </div>
              <span class="text-[13px] font-medium text-fg-muted">进入 ›</span>
            </button>

            <!-- Enabled Models Whitelist for Work Composer -->
            <section class="rounded-2xl bg-surface/65 p-5 space-y-4">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 class="text-[15.5px] font-semibold text-fg">输入框可用模型列表</h2>
                  <p class="mt-0.5 text-[12px] text-fg-muted">
                    控制哪些模型会出现在 Work 输入框选择器中（当前已启用 {{ enabledCount }} / {{ runtime.allModels.length }}）
                  </p>
                </div>
                <div class="flex items-center gap-2">
                  <BaseButton size="sm" variant="ghost" @click="enableAllModels">恢复全选</BaseButton>
                </div>
              </div>

              <input
                v-model="modelFilter"
                type="text"
                placeholder="筛选模型名称或 Provider…"
                class="focus-ring w-full rounded-xl bg-canvas px-3.5 py-2 text-[12.5px] text-fg outline-none placeholder:text-fg-faint"
              />

              <div v-if="!groupedAllModels.length" class="py-6 text-center text-[12.5px] text-fg-faint">
                暂未发现匹配模型，请点击上方「管理 Provider 与自定义模型」添加。
              </div>

              <div v-else class="space-y-4">
                <div v-for="group in groupedAllModels" :key="group.providerID" class="space-y-1.5">
                  <p class="px-1 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">
                    {{ group.providerID }}
                  </p>
                  <div class="space-y-1">
                    <div
                      v-for="m in group.items"
                      :key="m.ref"
                      class="flex items-center justify-between gap-3 rounded-xl bg-canvas/75 px-3.5 py-2"
                    >
                      <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2">
                          <span class="truncate font-mono text-[12.5px] font-medium text-fg">{{ m.modelID }}</span>
                          <span v-if="m.variants?.length" class="rounded bg-surface px-1.5 py-0.5 text-[10px] text-fg-faint">
                            {{ m.variants.join("/") }}
                          </span>
                          <span
                            v-if="(runtime.settings?.model.default_composer_model || cfg?.default_model) === m.ref"
                            class="rounded-full bg-accent-weak px-2 py-0.5 text-[10px] font-medium text-accent"
                          >
                            默认
                          </span>
                        </div>
                      </div>

                      <div class="flex shrink-0 items-center gap-3">
                        <button
                          v-if="(runtime.settings?.model.default_composer_model || cfg?.default_model) !== m.ref"
                          type="button"
                          class="text-[11.5px] text-fg-faint transition-colors hover:text-fg"
                          @click="setDefaultComposerModel(m.ref)"
                        >
                          设为默认
                        </button>
                        <button
                          type="button"
                          role="switch"
                          :aria-checked="isModelEnabled(m.ref)"
                          class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors"
                          :style="{ background: isModelEnabled(m.ref) ? 'var(--work-accent)' : 'var(--hover)' }"
                          @click="toggleModelEnabled(m.ref)"
                        >
                          <span
                            class="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform"
                            :class="isModelEnabled(m.ref) ? 'translate-x-4.5' : 'translate-x-1'"
                          />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </template>

          <!-- PRIMARY TAB 2: Permissions, MCP & Global Instructions -->
          <template v-else-if="activeTab === 'instructions'">
            <section class="rounded-2xl bg-surface/65 p-5 space-y-4">
              <h2 class="text-[15.5px] font-semibold text-fg">工具权限与全局系统指令</h2>

              <!-- Full Command Mode Switch Card -->
              <div class="flex items-center justify-between gap-3 rounded-xl bg-canvas/85 px-4 py-3">
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="text-[13.5px] font-semibold text-fg">完全命令模式（自动通过全部终端命令）</span>
                    <span
                      v-if="fullCommandMode"
                      class="rounded-full bg-danger-weak px-2 py-0.5 text-[10.5px] font-medium text-danger"
                    >
                      已启用
                    </span>
                  </div>
                  <p class="mt-0.5 text-[12px] text-fg-muted">
                    开启前需确认安全警告；启用后将自动批准全部 <code class="rounded bg-surface px-1 font-mono text-[11px]">bash</code> 终端命令，避免批处理中断阻塞。
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  :aria-checked="fullCommandMode"
                  class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors"
                  :style="{ background: fullCommandMode ? 'var(--danger)' : 'var(--hover)' }"
                  @click="toggleFullCommandFromSettings"
                >
                  <span
                    class="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform"
                    :class="fullCommandMode ? 'translate-x-4.5' : 'translate-x-1'"
                  />
                </button>
              </div>

              <div>
                <span class="text-[12px] font-medium text-fg-muted">OpenCode 工具权限预设 (config.permission)</span>
                <div class="mt-2 grid grid-cols-3 gap-2">
                  <button
                    v-for="item in [
                      { key: 'smart', label: '智能审批（推荐）' },
                      { key: 'allow_all', label: '全自动允许' },
                      { key: 'ask_all', label: '始终询问确认' },
                    ]"
                    :key="item.key"
                    type="button"
                    class="focus-ring rounded-xl px-3 py-2.5 text-[12.5px] transition-colors"
                    :class="permissionPreset === item.key ? 'bg-canvas font-semibold text-fg ring-2 ring-[color:var(--work-accent)]' : 'bg-canvas/55 text-fg-muted hover:text-fg'"
                    @click="permissionPreset = item.key as any"
                  >
                    {{ item.label }}
                  </button>
                </div>
              </div>

              <label class="block">
                <span class="text-[12px] font-medium text-fg-muted">轻量辅助模型 (config.small_model，可选)</span>
                <input
                  v-model="smallModel"
                  type="text"
                  placeholder="例如 deepseek/deepseek-chat（用于生成标题/压缩上下文）"
                  class="focus-ring mt-1.5 w-full rounded-xl bg-canvas px-3.5 py-2 font-mono text-[12.5px] text-fg outline-none"
                />
              </label>

              <label class="block">
                <span class="text-[12px] font-medium text-fg-muted">全局 AGENTS.md (~/.config/opencode/AGENTS.md)</span>
                <textarea
                  v-model="agentsMd"
                  rows="6"
                  placeholder="填写所有项目共用的编码规范、语言偏好与工具约束…"
                  class="focus-ring mt-1.5 w-full rounded-xl bg-canvas px-3.5 py-2.5 text-[13px] leading-relaxed text-fg outline-none"
                />
              </label>

              <div class="flex items-center gap-3">
                <BaseButton size="sm" :loading="savingInstructions" @click="saveInstructionsAndPerms">保存并同步 OpenCode</BaseButton>
                <span v-if="instructionsMsg" class="text-[12px]" style="color: var(--success)">{{ instructionsMsg }}</span>
              </div>
            </section>

            <!-- Secondary Links: MCP & Raw Config -->
            <div class="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                class="focus-ring flex items-center justify-between rounded-2xl bg-surface/65 p-4 text-left transition-colors hover:bg-surface"
                @click="openSubPage('mcp')"
              >
                <div>
                  <p class="text-[14px] font-semibold text-fg">MCP 服务器管理</p>
                  <p class="mt-0.5 text-[12px] text-fg-faint">已配置 {{ runtime.mcpServers.length }} 个扩展服务</p>
                </div>
                <span class="text-[13px] text-fg-muted">›</span>
              </button>

              <button
                type="button"
                class="focus-ring flex items-center justify-between rounded-2xl bg-surface/65 p-4 text-left transition-colors hover:bg-surface"
                @click="openSubPage('raw-config')"
              >
                <div>
                  <p class="text-[14px] font-semibold text-fg">编辑原始 opencode.json</p>
                  <p class="mt-0.5 text-[12px] text-fg-faint">高级 JSON 视图与目录快捷跳转</p>
                </div>
                <span class="text-[13px] text-fg-muted">›</span>
              </button>
            </div>
          </template>

          <!-- PRIMARY TAB 3: Workspaces & Skills -->
          <template v-else-if="activeTab === 'workspace'">
            <section class="rounded-2xl bg-surface/65 p-5 space-y-3.5">
              <div class="flex items-center justify-between">
                <div>
                  <h2 class="text-[15.5px] font-semibold text-fg">已添加项目文件夹</h2>
                  <p class="mt-0.5 text-[12px] text-fg-muted">侧栏 Projects 树会按以下项目分组并支持多任务并行。</p>
                </div>
                <BaseButton size="sm" @click="work.pickWorkspace()">+ 添加项目</BaseButton>
              </div>

              <div v-if="work.workspaces.length" class="space-y-2">
                <div
                  v-for="ws in work.workspaces"
                  :key="ws.id"
                  class="flex items-center justify-between gap-3 rounded-xl bg-canvas/75 px-3.5 py-2.5"
                >
                  <div class="min-w-0 flex-1">
                    <p class="text-[13.5px] font-medium text-fg">{{ ws.name }}</p>
                    <p class="truncate font-mono text-[11px] text-fg-faint">{{ ws.path }}</p>
                  </div>
                  <div class="flex shrink-0 gap-2">
                    <BaseButton size="sm" variant="ghost" @click="work.openInExplorer(ws.path)">打开目录</BaseButton>
                    <BaseButton size="sm" variant="ghost" @click="work.removeWorkspace(ws.path)">移除</BaseButton>
                  </div>
                </div>
              </div>
              <p v-else class="py-4 text-center text-[12.5px] text-fg-faint">尚未添加本地项目。</p>
            </section>

            <section class="rounded-2xl bg-surface/65 p-5 space-y-3.5">
              <div class="flex items-center justify-between">
                <div>
                  <h2 class="text-[15.5px] font-semibold text-fg">本机 OpenCode 技能</h2>
                  <p class="mt-0.5 text-[12px] text-fg-muted">扫描当前项目与全局技能目录提供，输入 <code class="rounded bg-canvas px-1">/</code> 即可激活。</p>
                </div>
                <BaseButton size="sm" variant="ghost" @click="work.loadSkills()">刷新</BaseButton>
              </div>
              <div v-if="work.skills.length" class="grid gap-2 sm:grid-cols-2">
                <div v-for="skill in work.skills" :key="skill.name" class="rounded-xl bg-canvas/75 p-3">
                  <p class="text-[13px] font-medium text-fg">{{ skill.name }}</p>
                  <p v-if="skill.description" class="mt-1 line-clamp-2 text-[11.5px] text-fg-muted">{{ skill.description }}</p>
                </div>
              </div>
              <p v-else class="py-4 text-center text-[12.5px] text-fg-faint">暂未发现 OpenCode 技能。</p>
            </section>
          </template>

          <!-- PRIMARY TAB 4: Runtime & Account -->
          <template v-else>
            <section class="rounded-2xl bg-surface/65 p-5 space-y-4">
              <h2 class="text-[15.5px] font-semibold text-fg">本地 OpenCode 运行时</h2>
              <dl class="grid gap-2.5 text-[12.5px] sm:grid-cols-2">
                <div class="rounded-xl bg-canvas/75 px-3.5 py-2.5">
                  <dt class="text-[11px] text-fg-faint">运行状态</dt>
                  <dd class="mt-0.5 font-medium text-fg">{{ runtime.status?.state ?? "未知" }}</dd>
                </div>
                <div class="rounded-xl bg-canvas/75 px-3.5 py-2.5">
                  <dt class="text-[11px] text-fg-faint">版本 / 来源</dt>
                  <dd class="mt-0.5 text-fg">{{ runtime.status?.version ?? "未安装" }} · {{ sourceLabel }}</dd>
                </div>
                <div class="rounded-xl bg-canvas/75 px-3.5 py-2.5 sm:col-span-2">
                  <dt class="text-[11px] text-fg-faint">可执行路径</dt>
                  <dd class="mt-0.5 break-all font-mono text-[11.5px] text-fg">{{ runtime.status?.exe_path ?? "—" }}</dd>
                </div>
              </dl>

              <div class="flex gap-2">
                <input
                  v-model="customExe"
                  type="text"
                  placeholder="自定义 opencode.exe 路径（留空自动探测）"
                  class="focus-ring min-w-0 flex-1 rounded-xl bg-canvas px-3 py-2 font-mono text-[12px] text-fg outline-none"
                />
                <BaseButton size="sm" variant="secondary" @click="pickCustomExe">浏览</BaseButton>
                <BaseButton size="sm" :loading="savingRuntime" @click="saveCustomExe">保存</BaseButton>
              </div>

              <div class="flex flex-wrap gap-2">
                <BaseButton size="sm" variant="secondary" :loading="runtime.busy" @click="runtime.restart()">重启 OpenCode</BaseButton>
                <BaseButton size="sm" variant="ghost" @click="runtime.redetect()">重新检测</BaseButton>
                <BaseButton size="sm" variant="ghost" @click="openLogs">打开日志</BaseButton>
                <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-setup' })">安装指引</BaseButton>
              </div>
              <p v-if="runtimeMsg" class="text-[12px]" style="color: var(--success)">{{ runtimeMsg }}</p>
            </section>

            <section class="rounded-2xl bg-surface/65 p-5 space-y-3">
              <h2 class="text-[15.5px] font-semibold text-fg">账号与策略状态</h2>
              <p class="text-[12.5px] text-fg-muted">
                {{ desktop.loggedIn ? `已登录：${desktop.user?.display_name ?? ""}（${desktop.user?.email ?? ""}）` : "未登录：仍可使用本地 Provider 与密钥，Whitz 内置模型不可用。" }}
              </p>
              <p class="text-[12px] text-fg-faint">
                Work 策略：{{ desktop.workEnabled ? "已启用" : "已禁用" }} · 来源：{{ desktop.policy?.source ?? "default" }}
              </p>
              <div class="flex gap-2">
                <BaseButton v-if="!desktop.loggedIn" size="sm" @click="router.push({ name: 'login' })">去登录</BaseButton>
                <BaseButton v-else size="sm" variant="secondary" @click="desktop.logout().then(() => router.push({ name: 'work' }))">
                  退出登录
                </BaseButton>
                <BaseButton size="sm" variant="ghost" @click="desktop.refreshPolicy()">刷新策略</BaseButton>
              </div>
            </section>
          </template>
        </div>
      </div>
    </div>
    <FullCommandConfirmModal
      :open="fullCommandConfirmOpen"
      @close="fullCommandConfirmOpen = false"
      @confirm="confirmFullCommandFromSettings"
    />
  </div>
</template>
