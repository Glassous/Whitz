<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { PROVIDER_PRESETS, type ProviderProtocol, type WorkSettings } from "@shared/work-types";
import { useDesktopStore } from "../../stores/desktop";
import { useRuntimeStore } from "../../stores/runtime";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{ settings: WorkSettings }>();
const emit = defineEmits<{ saved: [] }>();

const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const router = useRouter();

const protocol = ref<ProviderProtocol>(props.settings.model.protocol);
const baseUrl = ref(props.settings.model.base_url);
const model = ref(props.settings.model.model);
const apiKey = ref("");
const supportsVision = ref(props.settings.model.supports_vision);
const approvals = ref(props.settings.model.approvals);

const saving = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);
const testing = ref(false);
const testResult = ref<{ ok: boolean; latency_ms: number | null; model: string | null; detail: string | null } | null>(null);

watch(
  () => props.settings,
  (next) => {
    protocol.value = next.model.protocol;
    baseUrl.value = next.model.base_url;
    model.value = next.model.model;
    supportsVision.value = next.model.supports_vision;
    approvals.value = next.model.approvals;
  },
  { deep: true },
);

const preset = computed(() => PROVIDER_PRESETS.find((item) => item.protocol === protocol.value));
const isBuiltin = computed(() => protocol.value === "builtin");
const builtinBlocked = computed(() => isBuiltin.value && !desktop.loggedIn);
const keyPlaceholder = computed(() =>
  props.settings.model.api_key_set ? "已保存（留空则不修改）" : isBuiltin.value ? "登录后自动获取" : "sk-…",
);

function pick(protocolValue: ProviderProtocol) {
  if (protocolValue === "builtin" && !desktop.loggedIn) return;
  protocol.value = protocolValue;
  message.value = null;
  error.value = null;
  const found = PROVIDER_PRESETS.find((item) => item.protocol === protocolValue);
  if (found) {
    baseUrl.value = found.base_url;
    model.value = found.models[0] ?? "";
  }
  if (protocolValue === "builtin") {
    baseUrl.value = "";
    model.value = "";
  }
}

async function save() {
  saving.value = true;
  message.value = null;
  error.value = null;
  try {
    await runtime.saveSettings({
      protocol: protocol.value,
      base_url: baseUrl.value.trim(),
      model: model.value.trim(),
      supports_vision: supportsVision.value,
      approvals: approvals.value,
      api_key: apiKey.value.trim() || undefined,
    });
    apiKey.value = "";
    message.value = "模型配置已保存到本机";
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function test() {
  testing.value = true;
  testResult.value = null;
  try {
    if (apiKey.value.trim()) {
      await runtime.saveSettings({
        protocol: protocol.value,
        base_url: baseUrl.value.trim(),
        model: model.value.trim(),
        api_key: apiKey.value.trim(),
      });
      apiKey.value = "";
    }
    testResult.value = await runtime.testModel();
  } catch (err) {
    testResult.value = {
      ok: false,
      latency_ms: null,
      model: null,
      detail: err instanceof Error ? err.message : "连通性测试失败",
    };
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="space-y-5">
    <div>
      <p class="text-[12px] font-medium text-fg-muted">模型接入</p>
      <div class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <button
          v-for="option in PROVIDER_PRESETS"
          :key="option.protocol"
          type="button"
          class="focus-ring rounded-xl border px-3 py-2.5 text-left text-[12.5px] transition-colors"
          :class="
            protocol === option.protocol
              ? 'border-[color:var(--work-accent)] bg-[color:var(--work-accent-weak)] text-fg'
              : 'border-line bg-canvas text-fg-muted hover:border-line-strong hover:text-fg'
          "
          @click="pick(option.protocol)"
        >
          <span class="block font-medium">{{ option.label }}</span>
          <span class="mt-0.5 block text-[11px] text-fg-faint">{{ option.hint }}</span>
        </button>
        <button
          type="button"
          class="focus-ring rounded-xl border px-3 py-2.5 text-left text-[12.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          :class="
            protocol === 'builtin'
              ? 'border-[color:var(--work-accent)] bg-[color:var(--work-accent-weak)] text-fg'
              : 'border-line bg-canvas text-fg-muted hover:border-line-strong hover:text-fg'
          "
          :disabled="!desktop.loggedIn"
          :title="desktop.loggedIn ? '使用账号共享额度' : '登录后可用'"
          @click="pick('builtin')"
        >
          <span class="block font-medium">Whitz 内置</span>
          <span class="mt-0.5 block text-[11px] text-fg-faint">共享账号额度</span>
        </button>
      </div>
    </div>

    <div v-if="!isBuiltin" class="grid gap-3 sm:grid-cols-2">
      <label class="block">
        <span class="text-[12px] font-medium text-fg-muted">接口地址</span>
        <input
          v-model="baseUrl"
          type="url"
          spellcheck="false"
          class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint"
          :placeholder="preset?.base_url || 'https://api.example.com/v1'"
        />
      </label>
      <label class="block">
        <span class="text-[12px] font-medium text-fg-muted">模型名称</span>
        <input
          v-model="model"
          type="text"
          spellcheck="false"
          class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint"
          :placeholder="preset?.models[0] || 'model-name'"
        />
      </label>
      <label class="block sm:col-span-2">
        <span class="text-[12px] font-medium text-fg-muted">API Key</span>
        <input
          v-model="apiKey"
          type="password"
          autocomplete="off"
          class="focus-ring mt-1.5 w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint"
          :placeholder="keyPlaceholder"
        />
        <span class="mt-1 block text-[11px] text-fg-faint">Key 仅保存在本机（Windows DPAPI 加密），不会上传云端。</span>
      </label>
    </div>

    <div v-else class="rounded-2xl border border-line bg-surface/60 px-4 py-3 text-[12.5px] text-fg-muted">
      <p>内置模型由 Whitz 服务端代理并计入账号积分，桌面端不会持有平台 Key。</p>
      <p v-if="builtinBlocked" class="mt-1 text-warning">使用内置模型需要先登录 Whitz 账号。</p>
      <div class="mt-2 flex items-center gap-3">
        <BaseButton v-if="!desktop.loggedIn" size="sm" variant="secondary" @click="router.push({ name: 'login' })">
          去登录
        </BaseButton>
        <span v-else class="text-[11px] text-fg-faint">额度与网页 Chat 共享，超出后自动停止。</span>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-4">
      <label class="flex items-center gap-2 text-[12.5px] text-fg-muted">
        <input v-model="supportsVision" type="checkbox" class="h-4 w-4 rounded accent-[color:var(--work-accent)]" />
        模型支持图片输入
      </label>
      <label class="flex items-center gap-2 text-[12.5px] text-fg-muted">
        审批
        <select
          v-model="approvals"
          class="focus-ring rounded-lg border border-line bg-canvas px-2 py-1 text-[12px] text-fg"
        >
          <option value="smart">智能审批</option>
          <option value="manual">每次询问</option>
          <option value="off">不询问</option>
        </select>
      </label>
    </div>

    <div class="flex flex-wrap items-center gap-3">
      <BaseButton :loading="saving" :disabled="builtinBlocked" @click="save">保存配置</BaseButton>
      <BaseButton variant="secondary" :loading="testing" :disabled="builtinBlocked" @click="test">测试连通性</BaseButton>
      <span v-if="message" class="text-[12px]" style="color: var(--success)">{{ message }}</span>
      <span v-if="error" class="text-[12px] text-danger">{{ error }}</span>
    </div>

    <div
      v-if="testResult"
      class="rounded-xl border px-3.5 py-2.5 text-[12px]"
      :class="testResult.ok ? 'border-line bg-success-weak/40' : 'border-line bg-danger-weak/40'"
    >
      <p :class="testResult.ok ? '' : 'text-danger'">
        {{ testResult.ok ? `连接正常 · ${testResult.latency_ms ?? 0}ms · ${testResult.model ?? ""}` : `连接失败：${testResult.detail ?? ""}` }}
      </p>
    </div>
  </div>
</template>
