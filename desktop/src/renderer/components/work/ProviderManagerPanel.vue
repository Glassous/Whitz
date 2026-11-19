<script setup lang="ts">
import { computed, ref } from "vue";
import { OPENCODE_PROVIDER_TEMPLATES, type OpenCodeProviderInfo, type OpenCodeProviderModelInput } from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import BaseButton from "@web/components/ui/BaseButton.vue";

const runtime = useRuntimeStore();

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

function openTemplate(tplId: string) {
  const tpl = OPENCODE_PROVIDER_TEMPLATES.find((t) => t.id === tplId);
  if (!tpl) return;
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
  } catch (err) {
    error.value = err instanceof Error ? err.message : "移除失败";
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="space-y-5">
    <!-- Quick Add Templates Card -->
    <div class="rounded-2xl bg-surface/65 p-5">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 class="text-[15px] font-semibold text-fg">添加服务商或自定义兼容接口</h2>
          <p class="mt-0.5 text-[12.5px] text-fg-muted">
            配置直接写入 <code class="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px]">opencode.json</code> 与 <code class="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px]">auth.json</code>，与命令行完全互通。
          </p>
        </div>
      </div>

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

    <!-- Custom Provider & Custom Model Editor -->
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

      <!-- Visual Custom Models Editor -->
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
              placeholder="模型 ID（如 deepseek-reasoner）"
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
            placeholder="输入新模型 ID（回车或点击添加）"
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

    <!-- Existing Providers Cards -->
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

    <p v-if="message" class="text-[12.5px]" style="color: var(--success)">{{ message }}</p>
    <p v-if="error" class="text-[12.5px] text-danger">{{ error }}</p>
  </div>
</template>
