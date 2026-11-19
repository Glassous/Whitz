<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  OPENCODE_PROVIDER_TEMPLATES,
  type OpenCodePermissionPreset,
  type WorkAccessMode,
  type WorkSettings,
} from "@shared/work-types";
import { useDesktopStore } from "../../stores/desktop";
import { useRuntimeStore } from "../../stores/runtime";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{ settings: WorkSettings }>();
const emit = defineEmits<{ saved: [] }>();

const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const router = useRouter();

const mode = ref<WorkAccessMode>(props.settings.model.mode);
const defaultModel = ref(runtime.opencodeConfig?.default_model ?? "");
const smallModel = ref(runtime.opencodeConfig?.small_model ?? "");
const permissionPreset = ref<Exclude<OpenCodePermissionPreset, "custom">>(
  runtime.opencodeConfig?.permission_preset === "custom" ? "smart" : (runtime.opencodeConfig?.permission_preset ?? "smart"),
);

const savingMode = ref(false);
const savingPrefs = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);
const copiedGateway = ref(false);
const testing = ref(false);
const testResult = ref<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null } | null>(null);

// Provider editor state (directly writes ~/.config/opencode/opencode.json & auth)
const editorOpen = ref(false);
const editingId = ref("");
const editingName = ref("");
const editingNpm = ref("@ai-sdk/openai-compatible");
const editingBaseUrl = ref("");
const editingModelsText = ref("");
const editingApiKey = ref("");
const savingProvider = ref(false);

watch(
  () => props.settings,
  (next) => {
    mode.value = next.model.mode;
  },
  { deep: true },
);

watch(
  () => runtime.opencodeConfig,
  (cfg) => {
    if (!cfg) return;
    defaultModel.value = cfg.default_model;
    smallModel.value = cfg.small_model;
    permissionPreset.value = cfg.permission_preset === "custom" ? "smart" : cfg.permission_preset;
  },
  { immediate: true, deep: true },
);

const cfg = computed(() => runtime.opencodeConfig);
const isBuiltin = computed(() => mode.value === "builtin");
const gatewayUrl = computed(() => runtime.gateway?.base_url ?? cfg.value?.whitz_base_url ?? "启动中…");

async function switchMode(nextMode: WorkAccessMode) {
  if (nextMode === "builtin" && !desktop.loggedIn) return;
  mode.value = nextMode;
  savingMode.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.saveSettings({ mode: nextMode });
    message.value =
      nextMode === "builtin"
        ? cfg.value?.whitz_configured
          ? "已切换为 Whitz 内置模式（由原生 OpenCode 直连本机网关）"
          : "已切换为 Whitz 内置模式（通过 Work 内存桥接进入 OpenCode 模型列表）"
        : "已切换为接入本机 OpenCode 配置";
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "切换失败";
  } finally {
    savingMode.value = false;
  }
}

async function copyGatewayUrl() {
  if (!runtime.gateway?.base_url) return;
  try {
    await navigator.clipboard.writeText(runtime.gateway.base_url);
    copiedGateway.value = true;
    setTimeout(() => {
      copiedGateway.value = false;
    }, 1800);
  } catch {
    /* ignore */
  }
}

async function writeWhitzToConfig() {
  savingMode.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.writeWhitzToOpenCode();
    message.value = "已写入本机 ~/.config/opencode/opencode.json！后续将由原生 OpenCode 直接调用 Whitz 服务";
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "写入失败";
  } finally {
    savingMode.value = false;
  }
}

async function removeWhitzFromConfig() {
  savingMode.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.removeWhitzFromOpenCode();
    message.value = "已从 opencode.json 移除 Whitz，当前回退为 Work 内存桥接模式";
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "移除失败";
  } finally {
    savingMode.value = false;
  }
}

async function saveOpenCodePreferences() {
  savingPrefs.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.saveOpenCodeConfig({
      default_model: defaultModel.value.trim(),
      small_model: smallModel.value.trim(),
      permission_preset: permissionPreset.value,
    });
    message.value = "已直接同步保存至本机 opencode.json";
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    savingPrefs.value = false;
  }
}

function openTemplate(tplId: string) {
  const tpl = OPENCODE_PROVIDER_TEMPLATES.find((t) => t.id === tplId);
  if (!tpl) return;
  editorOpen.value = true;
  editingId.value = tpl.id === "custom" ? "" : tpl.id;
  editingName.value = tpl.label;
  editingNpm.value = tpl.npm;
  editingBaseUrl.value = tpl.baseURL;
  editingModelsText.value = tpl.models.join(", ");
  editingApiKey.value = "";
}

function editExistingProvider(id: string) {
  const found = cfg.value?.providers.find((p) => p.id === id);
  if (!found || found.source === "bridge") return;
  editorOpen.value = true;
  editingId.value = found.id;
  editingName.value = found.name;
  editingNpm.value = found.npm;
  editingBaseUrl.value = found.baseURL;
  editingModelsText.value = found.models.map((m) => m.id).join(", ");
  editingApiKey.value = "";
}

async function submitProvider() {
  const id = editingId.value.trim();
  if (!id) {
    error.value = "请填写 Provider ID（例如 openai、deepseek 或 myproxy）";
    return;
  }
  savingProvider.value = true;
  message.value = null;
  error.value = null;
  try {
    const models = editingModelsText.value
      .split(/[,，\n]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((mid) => ({ id: mid, name: mid }));
    await runtime.upsertOpenCodeProvider({
      id,
      name: editingName.value.trim() || id,
      npm: editingNpm.value.trim() || "@ai-sdk/openai-compatible",
      baseURL: editingBaseUrl.value.trim() || undefined,
      apiKey: editingApiKey.value.trim() || undefined,
      models,
      setCacheKey: true,
    });
    editorOpen.value = false;
    editingApiKey.value = "";
    message.value = `Provider「${id}」已写入本机 OpenCode 配置`;
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存 Provider 失败";
  } finally {
    savingProvider.value = false;
  }
}

async function deleteProvider(id: string) {
  savingProvider.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.deleteOpenCodeProvider(id);
    if (editingId.value === id) editorOpen.value = false;
    message.value = `已从本机 OpenCode 配置移除「${id}」`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  } finally {
    savingProvider.value = false;
  }
}

async function test() {
  testing.value = true;
  testResult.value = null;
  try {
    testResult.value = await runtime.testModel();
  } catch (err) {
    testResult.value = {
      ok: false,
      latency_ms: null,
      model: null,
      detail: err instanceof Error ? err.message : "测试失败",
    };
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- 1. Mode Switcher: Builtin vs Local OpenCode -->
    <div>
      <p class="text-[12px] font-medium text-fg-muted">Work 模型接入模式</p>
      <div class="mt-2 grid gap-2.5 sm:grid-cols-2">
        <button
          type="button"
          class="focus-ring rounded-xl border px-3.5 py-3 text-left text-[12.5px] transition-colors"
          :class="
            mode === 'opencode_local'
              ? 'border-[color:var(--work-accent)] bg-[color:var(--work-accent-weak)] text-fg'
              : 'border-line bg-canvas text-fg-muted hover:border-line-strong hover:text-fg'
          "
          :disabled="savingMode"
          @click="switchMode('opencode_local')"
        >
          <span class="block font-medium">接入本机 OpenCode</span>
          <span class="mt-0.5 block text-[11px] text-fg-faint">使用下方本机 OpenCode 配置模型（除选 whitz/* 外不消耗额度）</span>
        </button>

        <button
          type="button"
          class="focus-ring rounded-xl border px-3.5 py-3 text-left text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          :class="
            mode === 'builtin'
              ? 'border-[color:var(--work-accent)] bg-[color:var(--work-accent-weak)] text-fg'
              : 'border-line bg-canvas text-fg-muted hover:border-line-strong hover:text-fg'
          "
          :disabled="savingMode || !desktop.loggedIn"
          :title="desktop.loggedIn ? '固定走 Whitz 内置模型并共享账号额度' : '登录后可用'"
          @click="switchMode('builtin')"
        >
          <span class="block font-medium">Whitz 内置（共享额度）</span>
          <span class="mt-0.5 block text-[11px] text-fg-faint">通过本机 OpenAI 服务调用 Whitz 内置模型，与 Chat 共享额度</span>
        </button>
      </div>
    </div>

    <!-- 2. Localhost OpenAI Gateway + OpenCode Bridge / Native Card -->
    <div class="rounded-2xl border border-line bg-surface/50 p-4 text-[12.5px]">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="font-medium text-fg">Whitz 本机 OpenAI 协议服务（常驻运行）</p>
          <p class="mt-0.5 text-[11.5px] text-fg-muted">
            API Key 与 Model 名称可任意填写，外部工具与 OpenCode 调用均自动使用当前账号额度。
          </p>
        </div>
        <span
          class="rounded-full border border-line px-2 py-0.5 text-[10.5px]"
          :style="{ color: runtime.gateway?.running ? 'var(--success)' : 'var(--warning)' }"
        >
          {{ runtime.gateway?.running ? "运行中" : "启动中" }}
        </span>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-canvas px-3 py-2 font-mono text-[12px] text-fg">
        <span class="min-w-0 flex-1 truncate">{{ gatewayUrl }}</span>
        <BaseButton size="sm" variant="secondary" :disabled="!runtime.gateway?.base_url" @click="copyGatewayUrl">
          {{ copiedGateway ? "已复制" : "复制地址" }}
        </BaseButton>
      </div>

      <div v-if="!desktop.loggedIn" class="mt-2.5 flex items-center gap-3 text-[12px] text-warning">
        <span>未登录 Whitz 账号时，调用该内置服务会提示鉴权失败。</span>
        <BaseButton size="sm" variant="secondary" @click="router.push({ name: 'login' })">去登录</BaseButton>
      </div>

      <!-- Case 1 vs Case 2 indicator & One-click write -->
      <div class="mt-3 border-t border-line/70 pt-3">
        <div v-if="cfg?.whitz_configured" class="flex flex-wrap items-center justify-between gap-2.5">
          <div class="min-w-0 flex-1">
            <p class="text-[12px] font-medium" style="color: var(--success)">
              当前状态：本机 OpenCode 配置已写入 Whitz（原生直连模式，不开启内存桥接）
            </p>
            <p v-if="!cfg.whitz_port_matches" class="mt-0.5 text-[11.5px] text-warning">
              检测到配置中的端口（{{ cfg.whitz_base_url ? `现端口 ${cfg.whitz_base_url}` : "" }}）与当前不一致，可点击同步端口。
            </p>
          </div>
          <div class="flex gap-2">
            <BaseButton v-if="!cfg.whitz_port_matches" size="sm" variant="secondary" :loading="savingMode" @click="writeWhitzToConfig">
              同步端口
            </BaseButton>
            <BaseButton size="sm" variant="ghost" :loading="savingMode" @click="removeWhitzFromConfig">
              从 OpenCode 移除
            </BaseButton>
          </div>
        </div>

        <div v-else class="flex flex-wrap items-center justify-between gap-2.5">
          <div class="min-w-0 flex-1">
            <p class="text-[12px] font-medium text-fg">
              当前状态：本机 OpenCode 配置未含 Whitz（已在 Work 内临时桥接进模型列表，未改写你的文件）
            </p>
            <p class="mt-0.5 text-[11.5px] text-fg-faint">
              写入后可由原生 OpenCode 直接调用本机服务，且在命令行 <code class="rounded bg-canvas px-1">opencode</code> 中也可直接使用。
            </p>
          </div>
          <BaseButton size="sm" :loading="savingMode" @click="writeWhitzToConfig">
            一键写入本机 OpenCode 配置
          </BaseButton>
        </div>
      </div>
    </div>

    <!-- 3. Direct Local OpenCode Config Editor (model / small_model / permission) -->
    <div class="rounded-2xl border border-line bg-surface/35 p-4 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-[13px] font-medium text-fg">本机 OpenCode 默认模型与权限（直改 opencode.json）</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">{{ cfg?.config_file ?? "~/.config/opencode/opencode.json" }}</p>
        </div>
        <BaseButton size="sm" variant="ghost" @click="runtime.openOpenCodeConfigDir()">打开配置目录</BaseButton>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <label class="block">
          <span class="text-[12px] font-medium text-fg-muted">默认主模型 (config.model)</span>
          <select
            v-if="cfg?.available_models.length"
            v-model="defaultModel"
            class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[12.5px] text-fg"
          >
            <option value="">自动选择</option>
            <option v-for="m in cfg.available_models" :key="m.ref" :value="m.ref">
              {{ m.ref }} {{ m.is_whitz ? "· Whitz 共享额度" : "" }}
            </option>
          </select>
          <input
            v-model="defaultModel"
            type="text"
            spellcheck="false"
            placeholder="例如 relais/daily 或 whitz/whitz-default"
            class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-1.5 font-mono text-[12px] text-fg placeholder:text-fg-faint"
          />
        </label>

        <label class="block">
          <span class="text-[12px] font-medium text-fg-muted">轻量辅助模型 (config.small_model，可选)</span>
          <input
            v-model="smallModel"
            type="text"
            spellcheck="false"
            placeholder="例如 relais/cheap（留空同主模型）"
            class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-2 font-mono text-[12px] text-fg placeholder:text-fg-faint"
          />
        </label>
      </div>

      <div>
        <span class="text-[12px] font-medium text-fg-muted">OpenCode 工具权限策略 (config.permission)</span>
        <div class="mt-2 grid grid-cols-3 gap-2">
          <button
            v-for="item in [
              { key: 'smart', label: '智能审批（推荐）' },
              { key: 'allow_all', label: '全自动允许' },
              { key: 'ask_all', label: '始终询问确认' },
            ]"
            :key="item.key"
            type="button"
            class="focus-ring rounded-xl border px-3 py-2 text-[12px] transition-colors"
            :class="
              permissionPreset === item.key
                ? 'border-[color:var(--work-accent)] bg-[color:var(--work-accent-weak)] text-fg font-medium'
                : 'border-line bg-canvas text-fg-muted hover:text-fg'
            "
            @click="permissionPreset = item.key as any"
          >
            {{ item.label }}
          </button>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2.5">
        <BaseButton size="sm" :loading="savingPrefs" @click="saveOpenCodePreferences">写入 OpenCode 配置</BaseButton>
        <BaseButton size="sm" variant="secondary" :loading="testing" @click="test">测试当前通道</BaseButton>
        <span v-if="isBuiltin" class="text-[11.5px] text-fg-faint">当前 Whitz Work 对话走内置模型；上方配置仍同步供本机 OpenCode 使用。</span>
      </div>
    </div>

    <!-- 4. In-App Provider Manager (Replaces standalone OpenAI/Anthropic/Google forms) -->
    <div class="rounded-2xl border border-line bg-surface/35 p-4 space-y-3.5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-[13px] font-medium text-fg">本机 OpenCode Provider 管理（与命令行完全互通）</p>
          <p class="mt-0.5 text-[11.5px] text-fg-faint">添加或修改的模型接口直接保存在 opencode.json 与 auth.json 中。</p>
        </div>
      </div>

      <!-- Quick Templates -->
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="tpl in OPENCODE_PROVIDER_TEMPLATES"
          :key="tpl.id"
          type="button"
          class="focus-ring rounded-lg border border-line bg-canvas px-2.5 py-1 text-[11.5px] text-fg-muted hover:border-line-strong hover:text-fg"
          @click="openTemplate(tpl.id)"
        >
          + {{ tpl.label }}
        </button>
      </div>

      <!-- Existing Providers List -->
      <div v-if="cfg?.providers.length" class="grid gap-2 sm:grid-cols-2">
        <div
          v-for="p in cfg.providers"
          :key="p.id"
          class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium text-fg">{{ p.name }} <span class="font-mono text-[10.5px] text-fg-faint">({{ p.id }})</span></p>
              <p class="truncate text-[11px] text-fg-faint">{{ p.baseURL || p.npm }}</p>
            </div>
            <span class="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px]" :style="{ color: p.connected ? 'var(--success)' : 'var(--fg-faint)' }">
              {{ p.source === "bridge" ? "内存桥接" : p.source === "config" ? "配置" : p.source }}
            </span>
          </div>
          <p class="mt-1.5 truncate text-[11px] text-fg-muted">
            模型：{{ p.models.length ? p.models.map((m) => m.id).slice(0, 4).join(", ") : "默认清单" }}
          </p>
          <div v-if="p.source === 'config'" class="mt-2 flex gap-2">
            <button type="button" class="text-[11px] underline-offset-2 hover:underline text-fg" @click="editExistingProvider(p.id)">
              编辑
            </button>
            <button type="button" class="text-[11px] text-danger underline-offset-2 hover:underline" @click="deleteProvider(p.id)">
              删除
            </button>
          </div>
        </div>
      </div>

      <!-- Inline Add / Edit Provider Card -->
      <div v-if="editorOpen" class="rounded-xl border border-[color:var(--work-accent)]/50 bg-canvas p-4 space-y-3">
        <div class="flex items-center justify-between">
          <p class="text-[12.5px] font-medium text-fg">编辑本机 OpenCode Provider</p>
          <button type="button" class="text-[11.5px] text-fg-faint hover:text-fg" @click="editorOpen = false">取消</button>
        </div>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span class="text-[11.5px] text-fg-muted">Provider ID</span>
            <input v-model="editingId" type="text" placeholder="openai / deepseek / myproxy" class="focus-ring mt-1 w-full rounded-lg border border-line bg-canvas px-2.5 py-1.5 font-mono text-[12px] text-fg" />
          </label>
          <label class="block">
            <span class="text-[11.5px] text-fg-muted">SDK 适配器 (npm)</span>
            <select v-model="editingNpm" class="focus-ring mt-1 w-full rounded-lg border border-line bg-canvas px-2.5 py-1.5 font-mono text-[12px] text-fg">
              <option value="@ai-sdk/openai-compatible">@ai-sdk/openai-compatible</option>
              <option value="@ai-sdk/openai">@ai-sdk/openai</option>
              <option value="@ai-sdk/anthropic">@ai-sdk/anthropic</option>
              <option value="@ai-sdk/google">@ai-sdk/google</option>
            </select>
          </label>
          <label class="block sm:col-span-2">
            <span class="text-[11.5px] text-fg-muted">Base URL</span>
            <input v-model="editingBaseUrl" type="url" placeholder="https://api.example.com/v1" class="focus-ring mt-1 w-full rounded-lg border border-line bg-canvas px-2.5 py-1.5 font-mono text-[12px] text-fg" />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-[11.5px] text-fg-muted">模型 ID 列表（逗号分隔）</span>
            <input v-model="editingModelsText" type="text" placeholder="gpt-4o, gpt-4.1-mini" class="focus-ring mt-1 w-full rounded-lg border border-line bg-canvas px-2.5 py-1.5 font-mono text-[12px] text-fg" />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-[11.5px] text-fg-muted">API Key（留空保持原有密钥，写入本机 OpenCode 配置）</span>
            <input v-model="editingApiKey" type="password" autocomplete="off" placeholder="sk-…" class="focus-ring mt-1 w-full rounded-lg border border-line bg-canvas px-2.5 py-1.5 font-mono text-[12px] text-fg" />
          </label>
        </div>
        <div class="flex gap-2">
          <BaseButton size="sm" :loading="savingProvider" @click="submitProvider">保存到 opencode.json</BaseButton>
        </div>
      </div>
    </div>

    <div v-if="testResult" class="rounded-xl border border-line bg-surface/60 px-3.5 py-2.5 text-[12px]">
      <span :style="{ color: testResult.ok ? 'var(--success)' : 'var(--danger)' }">
        {{ testResult.ok ? `连通正常 · ${testResult.model ?? ""} · ${testResult.latency_ms}ms` : "测试失败" }}
      </span>
      <p v-if="testResult.detail" class="mt-0.5 text-fg-muted">{{ testResult.detail }}</p>
    </div>

    <p v-if="message" class="text-[12px]" style="color: var(--success)">{{ message }}</p>
    <p v-if="error" class="text-[12px]" style="color: var(--danger)">{{ error }}</p>
  </div>
</template>
