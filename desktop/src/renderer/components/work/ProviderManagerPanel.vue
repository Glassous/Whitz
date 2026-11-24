<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  OPENCODE_PROVIDER_TEMPLATES,
  type OpenCodeProviderInfo,
  type OpenCodeProviderModelInput,
  type WorkProviderCatalogItem,
  type WorkProviderOAuthStart,
} from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore } from "../../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";

const runtime = useRuntimeStore();
const work = useWorkStore();

const panelMode = ref<"catalog" | "custom">("catalog");
const catalogSearch = ref("");
const catalogLoading = ref(false);

// Quick API Key / OAuth state for Official Catalog
const activeCatalogProvider = ref<WorkProviderCatalogItem | null>(null);
const quickApiKey = ref("");
const oauthMethodIndex = ref(0);
const oauthState = ref<WorkProviderOAuthStart | null>(null);
const oauthCode = ref("");
const oauthBusy = ref(false);

// Custom Provider Editor state
const editorOpen = ref(false);
const editingId = ref("");
const editingName = ref("");
const editingNpm = ref("@ai-sdk/openai-compatible");
const editingBaseUrl = ref("");
const editingApiKey = ref("");
const editingModels = ref<Array<{ id: string; name: string; enableVariants: boolean }>>([]);
const autoEnableInComposer = ref(true);

const newModelId = ref("");
const newModelName = ref("");

const saving = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);

const cfg = computed(() => runtime.opencodeConfig);
const providers = computed<OpenCodeProviderInfo[]>(() => cfg.value?.providers ?? []);

const filteredCatalog = computed<WorkProviderCatalogItem[]>(() => {
  const q = catalogSearch.value.trim().toLowerCase();
  const list = runtime.providerCatalog;
  if (!q) return list.slice(0, 60);
  return list
    .filter(
      (p) =>
        p.id.toLowerCase().includes(q) ||
        p.name.toLowerCase().includes(q) ||
        p.sample_models.some((m) => m.toLowerCase().includes(q)),
    )
    .slice(0, 60);
});

async function refreshCatalog() {
  catalogLoading.value = true;
  try {
    await runtime.loadProviderCatalog(work.activeWorkspace?.path);
  } finally {
    catalogLoading.value = false;
  }
}

function selectCatalogProvider(item: WorkProviderCatalogItem) {
  activeCatalogProvider.value = item;
  quickApiKey.value = "";
  oauthState.value = null;
  oauthCode.value = "";
  message.value = null;
  error.value = null;
}

async function submitQuickApiKey() {
  if (!activeCatalogProvider.value || !quickApiKey.value.trim()) return;
  saving.value = true;
  error.value = null;
  message.value = null;
  try {
    await runtime.setProviderApiKey(activeCatalogProvider.value.id, quickApiKey.value.trim());
    message.value = `已成功为「${activeCatalogProvider.value.name}」配置 API Key`;
    quickApiKey.value = "";
    activeCatalogProvider.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "设置 API Key 失败";
  } finally {
    saving.value = false;
  }
}

async function startOAuth(item: WorkProviderCatalogItem, methodIdx: number) {
  oauthBusy.value = true;
  error.value = null;
  message.value = null;
  oauthMethodIndex.value = methodIdx;
  try {
    const started = await runtime.startProviderOAuth(item.id, methodIdx, undefined, work.activeWorkspace?.path);
    oauthState.value = started;
    if (started.method === "auto") {
      // Auto flow polls server callback immediately while user authorizes in browser
      await runtime.completeProviderOAuth(item.id, methodIdx, undefined, work.activeWorkspace?.path);
      oauthState.value = null;
      activeCatalogProvider.value = null;
      message.value = `「${item.name}」OAuth 认证已完成！`;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "OAuth 授权失败";
  } finally {
    oauthBusy.value = false;
  }
}

async function finishOAuthCode() {
  if (!activeCatalogProvider.value) return;
  oauthBusy.value = true;
  error.value = null;
  try {
    await runtime.completeProviderOAuth(
      activeCatalogProvider.value.id,
      oauthMethodIndex.value,
      oauthCode.value.trim() || undefined,
      work.activeWorkspace?.path,
    );
    message.value = `「${activeCatalogProvider.value.name}」OAuth 认证已完成！`;
    oauthState.value = null;
    oauthCode.value = "";
    activeCatalogProvider.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "完成 OAuth 回调失败";
  } finally {
    oauthBusy.value = false;
  }
}

function openTemplate(tplId: string) {
  const tpl = OPENCODE_PROVIDER_TEMPLATES.find((t) => t.id === tplId);
  if (!tpl) return;
  panelMode.value = "custom";
  message.value = null;
  error.value = null;
  editorOpen.value = true;
  editingId.value = tpl.id === "custom" ? "" : tpl.id;
  editingName.value = tpl.label;
  editingNpm.value = tpl.npm;
  editingBaseUrl.value = tpl.baseURL;
  editingApiKey.value = "";
  editingModels.value = tpl.models.map((mid) => ({ id: mid, name: mid, enableVariants: false }));
  autoEnableInComposer.value = true;
}

function editProvider(p: OpenCodeProviderInfo) {
  if (p.source === "bridge") return;
  panelMode.value = "custom";
  message.value = null;
  error.value = null;
  editorOpen.value = true;
  editingId.value = p.id;
  editingName.value = p.name;
  editingNpm.value = p.npm || "@ai-sdk/openai-compatible";
  editingBaseUrl.value = p.baseURL;
  editingApiKey.value = "";
  editingModels.value = p.models.map((m) => ({ id: m.id, name: m.name || m.id, enableVariants: false }));
  autoEnableInComposer.value = true;
}

function addModelRow() {
  const id = newModelId.value.trim();
  if (!id) return;
  if (editingModels.value.some((m) => m.id === id)) return;
  editingModels.value.push({
    id,
    name: newModelName.value.trim() || id,
    enableVariants: false,
  });
  newModelId.value = "";
  newModelName.value = "";
}

function removeModelRow(idx: number) {
  editingModels.value.splice(idx, 1);
}

async function submitProvider() {
  const id = editingId.value.trim();
  if (!id) {
    error.value = "请填写 Provider ID（例如 openai、deepseek 或 custom-proxy）";
    return;
  }
  saving.value = true;
  message.value = null;
  error.value = null;
  try {
    const models: OpenCodeProviderModelInput[] = editingModels.value
      .filter((m) => m.id.trim())
      .map((m) => ({
        id: m.id.trim(),
        name: m.name.trim() || m.id.trim(),
        ...(m.enableVariants
          ? {
              variants: {
                low: { reasoningEffort: "low" },
                medium: { reasoningEffort: "medium" },
                high: { reasoningEffort: "high" },
              },
            }
          : {}),
      }));

    await runtime.upsertOpenCodeProvider({
      id,
      name: editingName.value.trim() || id,
      npm: editingNpm.value.trim() || "@ai-sdk/openai-compatible",
      baseURL: editingBaseUrl.value.trim() || undefined,
      apiKey: editingApiKey.value.trim() || undefined,
      models,
      setCacheKey: true,
    });

    if (autoEnableInComposer.value && models.length) {
      const currentList = runtime.settings?.model.enabled_models;
      if (Array.isArray(currentList)) {
        const nextSet = new Set(currentList);
        for (const m of models) nextSet.add(`${id}/${m.id}`);
        await runtime.setEnabledModels(Array.from(nextSet));
      }
    }

    editorOpen.value = false;
    editingApiKey.value = "";
    message.value = `Provider「${id}」已保存并同步至本机 OpenCode`;
    void refreshCatalog();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function deleteProvider(id: string) {
  saving.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.deleteOpenCodeProvider(id);
    if (editingId.value === id) editorOpen.value = false;
    message.value = `已移除「${id}」`;
    void refreshCatalog();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "移除失败";
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  void refreshCatalog();
});
</script>

<template>
  <div class="space-y-5">
    <!-- Top Sub-tab Switcher -->
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-1 rounded-xl bg-surface p-1 text-[12.5px]">
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 font-medium transition-colors"
          :class="panelMode === 'catalog' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
          @click="panelMode = 'catalog'"
        >
          官方服务商目录 & OAuth ({{ runtime.providerCatalog.length }})
        </button>
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 font-medium transition-colors"
          :class="panelMode === 'custom' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
          @click="panelMode = 'custom'"
        >
          自定义兼容接口 ({{ providers.length }})
        </button>
      </div>
      <BaseButton size="sm" variant="ghost" :loading="catalogLoading" @click="refreshCatalog">刷新目录</BaseButton>
    </div>

    <p v-if="message" class="rounded-xl bg-success-weak px-3.5 py-2 text-[12.5px]" style="color: var(--success)">{{ message }}</p>
    <p v-if="error" class="rounded-xl bg-danger-weak px-3.5 py-2 text-[12.5px] text-danger">{{ error }}</p>

    <!-- MODE 1: Official 75+ OpenCode Provider Catalog + OAuth -->
    <template v-if="panelMode === 'catalog'">
      <!-- Active Auth Drawer for Selected Provider -->
      <div v-if="activeCatalogProvider" class="rounded-2xl bg-surface/90 p-5 space-y-4">
        <div class="flex items-center justify-between gap-2">
          <div>
            <h3 class="text-[14.5px] font-semibold text-fg">连接 {{ activeCatalogProvider.name }}</h3>
            <p class="mt-0.5 font-mono text-[11.5px] text-fg-faint">
              {{ activeCatalogProvider.id }} · {{ activeCatalogProvider.model_count }} 个可用模型
            </p>
          </div>
          <button type="button" class="text-[12px] text-fg-faint hover:text-fg" @click="activeCatalogProvider = null">关闭</button>
        </div>

        <!-- OAuth Methods -->
        <div v-if="activeCatalogProvider.has_oauth" class="space-y-2.5 rounded-xl bg-canvas/85 p-4">
          <p class="text-[12.5px] font-medium text-fg">OAuth 官方登录（浏览器授权）</p>
          <div class="flex flex-wrap gap-2">
            <template v-for="(m, idx) in activeCatalogProvider.auth_methods" :key="`${m.type}-${idx}`">
              <BaseButton
                v-if="m.type === 'oauth'"
                size="sm"
                :loading="oauthBusy"
                @click="startOAuth(activeCatalogProvider, idx)"
              >
                {{ m.label || "使用 OAuth 登录" }}
              </BaseButton>
            </template>
          </div>

          <div v-if="oauthState" class="mt-3 space-y-2.5 rounded-xl bg-surface p-3 text-[12px]">
            <p class="text-fg">{{ oauthState.instructions || "请在弹出的浏览器页面完成授权登录。" }}</p>
            <p class="truncate font-mono text-[11px] text-fg-faint">{{ oauthState.url }}</p>
            <div v-if="oauthState.method === 'code'" class="flex gap-2">
              <input
                v-model="oauthCode"
                type="text"
                placeholder="粘贴浏览器返回的授权码 (Code)…"
                class="focus-ring min-w-0 flex-1 rounded-xl bg-canvas px-3 py-1.5 font-mono text-[12px] text-fg outline-none"
                @keydown.enter.prevent="finishOAuthCode"
              />
              <BaseButton size="sm" :loading="oauthBusy" :disabled="!oauthCode.trim()" @click="finishOAuthCode">
                验证完成
              </BaseButton>
            </div>
          </div>
        </div>

        <!-- API Key Binding -->
        <div v-if="activeCatalogProvider.has_api_key" class="space-y-2 rounded-xl bg-canvas/85 p-4">
          <p class="text-[12.5px] font-medium text-fg">使用 API Key 认证（写入 auth.json）</p>
          <div class="flex gap-2">
            <input
              v-model="quickApiKey"
              type="password"
              autocomplete="off"
              placeholder="输入该服务商的 API Key…"
              class="focus-ring min-w-0 flex-1 rounded-xl bg-surface px-3 py-2 font-mono text-[12px] text-fg outline-none"
              @keydown.enter.prevent="submitQuickApiKey"
            />
            <BaseButton size="sm" :loading="saving" :disabled="!quickApiKey.trim()" @click="submitQuickApiKey">
              保存密钥
            </BaseButton>
          </div>
        </div>
      </div>

      <!-- Search & Grid -->
      <div class="space-y-3">
        <input
          v-model="catalogSearch"
          type="search"
          placeholder="搜索 75+ OpenCode 内置服务商或模型（如 anthropic、copilot、openai、openrouter、deepseek）…"
          class="focus-ring w-full rounded-xl bg-surface px-3.5 py-2 text-[12.5px] text-fg outline-none placeholder:text-fg-faint"
        />

        <div v-if="!filteredCatalog.length" class="rounded-2xl bg-surface/50 py-10 text-center text-[12.5px] text-fg-faint">
          {{ runtime.ready ? "未找到匹配服务商，可切换至「自定义兼容接口」手动添加。" : "等待 OpenCode 服务就绪后自动加载完整服务商目录…" }}
        </div>

        <div v-else class="grid gap-2.5 sm:grid-cols-2">
          <div
            v-for="item in filteredCatalog"
            :key="item.id"
            class="flex flex-col justify-between gap-2.5 rounded-2xl bg-surface/65 p-4 transition-colors hover:bg-surface/90"
          >
            <div>
              <div class="flex items-center justify-between gap-2">
                <div class="flex min-w-0 items-center gap-2">
                  <span
                    class="h-2 w-2 shrink-0 rounded-full"
                    :style="{ background: item.connected ? 'var(--success)' : 'var(--line-strong)' }"
                  />
                  <span class="truncate text-[13.5px] font-semibold text-fg">{{ item.name }}</span>
                </div>
                <span class="shrink-0 rounded-md bg-canvas px-1.5 py-0.5 font-mono text-[10.5px] text-fg-faint">
                  {{ item.id }}
                </span>
              </div>
              <p v-if="item.sample_models.length" class="mt-1.5 truncate font-mono text-[11px] text-fg-faint">
                {{ item.sample_models.join(", ") }}
              </p>
            </div>

            <div class="flex items-center justify-between gap-2 pt-1">
              <div class="flex items-center gap-1 text-[10.5px] text-fg-faint">
                <span v-if="item.has_oauth" class="rounded bg-accent-weak px-1.5 py-0.5 font-medium text-accent">OAuth</span>
                <span v-if="item.has_api_key" class="rounded bg-canvas px-1.5 py-0.5">API Key</span>
                <span>{{ item.model_count }} 模型</span>
              </div>
              <BaseButton
                size="sm"
                :variant="item.connected ? 'ghost' : 'secondary'"
                @click="selectCatalogProvider(item)"
              >
                {{ item.connected ? "重新认证" : "连接" }}
              </BaseButton>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- MODE 2: Custom Compatible Provider & Model Editor -->
    <template v-else>
      <div class="rounded-2xl bg-surface/65 p-5">
        <h2 class="text-[15px] font-semibold text-fg">添加自定义兼容接口</h2>
        <p class="mt-0.5 text-[12.5px] text-fg-muted">
          配置直接写入 <code class="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px]">opencode.json</code> 与 <code class="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px]">auth.json</code>，与命令行完全互通。
        </p>

        <div class="mt-3.5 flex flex-wrap gap-2">
          <button
            v-for="tpl in OPENCODE_PROVIDER_TEMPLATES"
            :key="tpl.id"
            type="button"
            class="focus-ring rounded-xl bg-canvas px-3 py-1.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="openTemplate(tpl.id)"
          >
            + {{ tpl.label }}
          </button>
        </div>
      </div>

      <!-- Custom Provider Editor -->
      <div v-if="editorOpen" class="rounded-2xl bg-surface/85 p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-[14.5px] font-semibold text-fg">
            {{ editingId ? `配置 Provider · ${editingId}` : "新增自定义 Provider" }}
          </h3>
          <button type="button" class="text-[12px] text-fg-faint hover:text-fg" @click="editorOpen = false">取消</button>
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <label class="block">
            <span class="text-[12px] text-fg-muted">Provider ID</span>
            <input
              v-model="editingId"
              type="text"
              placeholder="openai / deepseek / myproxy"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
            />
          </label>
          <label class="block">
            <span class="text-[12px] text-fg-muted">显示名称</span>
            <input
              v-model="editingName"
              type="text"
              placeholder="DeepSeek / 公司中转"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 text-[12.5px] text-fg outline-none"
            />
          </label>
          <label class="block">
            <span class="text-[12px] text-fg-muted">SDK 适配器 (npm)</span>
            <select
              v-model="editingNpm"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
            >
              <option value="@ai-sdk/openai-compatible">@ai-sdk/openai-compatible</option>
              <option value="@ai-sdk/openai">@ai-sdk/openai</option>
              <option value="@ai-sdk/anthropic">@ai-sdk/anthropic</option>
              <option value="@ai-sdk/google">@ai-sdk/google</option>
            </select>
          </label>
          <label class="block">
            <span class="text-[12px] text-fg-muted">API Key（留空保持原有密钥）</span>
            <input
              v-model="editingApiKey"
              type="password"
              autocomplete="off"
              placeholder="sk-…"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
            />
          </label>
          <label class="block sm:col-span-2">
            <span class="text-[12px] text-fg-muted">Base URL</span>
            <input
              v-model="editingBaseUrl"
              type="url"
              placeholder="https://api.example.com/v1"
              class="focus-ring mt-1 w-full rounded-xl bg-canvas px-3 py-2 font-mono text-[12.5px] text-fg outline-none"
            />
          </label>
        </div>

        <div class="space-y-2.5 pt-1">
          <div class="flex items-center justify-between">
            <span class="text-[12.5px] font-medium text-fg">自定义模型列表</span>
            <span class="text-[11px] text-fg-faint">可附带 low / medium / high 思考档位</span>
          </div>

          <div v-if="editingModels.length" class="space-y-1.5">
            <div
              v-for="(m, idx) in editingModels"
              :key="`${m.id}-${idx}`"
              class="flex flex-wrap items-center gap-2 rounded-xl bg-canvas px-3 py-2"
            >
              <input
                v-model="m.id"
                type="text"
                placeholder="模型 ID"
                class="min-w-0 flex-1 bg-transparent font-mono text-[12px] text-fg outline-none"
              />
              <input
                v-model="m.name"
                type="text"
                placeholder="显示别名"
                class="w-36 bg-transparent text-[12px] text-fg-muted outline-none"
              />
              <label class="flex cursor-pointer items-center gap-1 text-[11px] text-fg-faint">
                <input v-model="m.enableVariants" type="checkbox" class="accent-primary" />
                <span>思考档位</span>
              </label>
              <button
                type="button"
                class="text-[12px] text-danger opacity-80 hover:opacity-100"
                @click="removeModelRow(idx)"
              >
                移除
              </button>
            </div>
          </div>

          <div class="flex gap-2">
            <input
              v-model="newModelId"
              type="text"
              placeholder="输入新模型 ID（回车添加）"
              class="focus-ring min-w-0 flex-1 rounded-xl bg-canvas px-3 py-1.5 font-mono text-[12px] text-fg outline-none"
              @keydown.enter.prevent="addModelRow"
            />
            <input
              v-model="newModelName"
              type="text"
              placeholder="显示名（可选）"
              class="focus-ring w-32 rounded-xl bg-canvas px-3 py-1.5 text-[12px] text-fg outline-none"
              @keydown.enter.prevent="addModelRow"
            />
            <BaseButton size="sm" variant="secondary" @click="addModelRow">+ 添加模型</BaseButton>
          </div>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 pt-1">
          <label class="flex cursor-pointer items-center gap-2 text-[12px] text-fg-muted">
            <input v-model="autoEnableInComposer" type="checkbox" class="accent-primary" />
            <span>保存后同步启用这些模型至输入框选择器</span>
          </label>
          <div class="flex gap-2">
            <BaseButton size="sm" variant="ghost" @click="editorOpen = false">取消</BaseButton>
            <BaseButton size="sm" :loading="saving" @click="submitProvider">保存到 OpenCode</BaseButton>
          </div>
        </div>
      </div>

      <!-- Existing Configured Providers -->
      <div class="space-y-3">
        <div
          v-for="p in providers"
          :key="p.id"
          class="rounded-2xl bg-surface/65 p-4 transition-colors hover:bg-surface/85"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span
                  class="h-2 w-2 rounded-full"
                  :style="{ background: p.connected ? 'var(--success)' : 'var(--fg-faint)' }"
                />
                <span class="text-[14px] font-semibold text-fg">{{ p.name }}</span>
                <span class="rounded-md bg-canvas px-1.5 py-0.5 font-mono text-[11px] text-fg-faint">{{ p.id }}</span>
                <span v-if="p.has_key" class="rounded-md bg-canvas px-1.5 py-0.5 text-[10.5px] text-fg-muted">已配密钥</span>
              </div>
              <p class="mt-1 truncate font-mono text-[11.5px] text-fg-faint">{{ p.baseURL || p.npm }}</p>
            </div>

            <div v-if="p.source === 'config'" class="flex shrink-0 items-center gap-1.5">
              <BaseButton size="sm" variant="ghost" @click="editProvider(p)">编辑</BaseButton>
              <BaseButton size="sm" variant="ghost" @click="deleteProvider(p.id)">移除</BaseButton>
            </div>
            <span v-else class="rounded-lg bg-canvas px-2 py-0.5 text-[11px] text-fg-faint">
              {{ p.source === "bridge" ? "内存桥接" : p.source }}
            </span>
          </div>

          <div v-if="p.models.length" class="mt-3 flex flex-wrap gap-1.5">
            <span
              v-for="m in p.models.slice(0, 12)"
              :key="m.id"
              class="rounded-lg bg-canvas px-2 py-0.5 font-mono text-[11px] text-fg-muted"
            >
              {{ m.id }}
            </span>
            <span v-if="p.models.length > 12" class="px-1.5 py-0.5 text-[11px] text-fg-faint">
              +{{ p.models.length - 12 }} 更多
            </span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
