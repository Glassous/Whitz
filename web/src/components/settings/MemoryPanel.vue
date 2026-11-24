<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import type { MemoryEntry, MemoryOverview, MemoryPendingItem } from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import FormError from "../ui/FormError.vue";
import Spinner from "../ui/Spinner.vue";

type TargetFilter = "all" | "memory" | "user";

const auth = useAuthStore();

const overview = ref<MemoryOverview | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const feedback = ref<string | null>(null);

const settingsSaving = ref(false);
const modalError = ref<string | null>(null);

const targetFilter = ref<TargetFilter>("all");

// Add entry state
const addFormOpen = ref(false);
const newTarget = ref<"memory" | "user">("memory");
const newContent = ref("");
const addingEntry = ref(false);
const addError = ref<string | null>(null);

// Inline edit entry state
const editingId = ref<string | null>(null);
const editTarget = ref<"memory" | "user">("memory");
const editContent = ref("");
const savingEdit = ref(false);
const deletingId = ref<string | null>(null);

// Pending proposals state
const pendingEditId = ref<string | null>(null);
const pendingEditContent = ref("");
const resolvingPendingId = ref<string | null>(null);

// Clear all confirmation modal
const clearModalOpen = ref(false);
const clearingAll = ref(false);

function extractError(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

const memoryEnabled = computed(() => overview.value?.memory_enabled ?? true);
const requireConfirm = computed(() => overview.value?.memory_require_confirm ?? false);
const entries = computed<MemoryEntry[]>(() => overview.value?.entries ?? []);
const pending = computed<MemoryPendingItem[]>(() => overview.value?.pending ?? []);

const memoryCharCount = computed(() => overview.value?.memory_char_count ?? overview.value?.char_count ?? 0);
const memoryCharLimit = computed(() => overview.value?.memory_char_limit ?? overview.value?.char_limit ?? 2200);
const userCharCount = computed(() => overview.value?.user_char_count ?? 0);
const userCharLimit = computed(() => overview.value?.user_char_limit ?? 1375);

const memoryPercent = computed(() =>
  memoryCharLimit.value > 0 ? Math.min(100, Math.round((memoryCharCount.value / memoryCharLimit.value) * 100)) : 0,
);
const userPercent = computed(() =>
  userCharLimit.value > 0 ? Math.min(100, Math.round((userCharCount.value / userCharLimit.value) * 100)) : 0,
);

function barClass(pct: number): string {
  if (pct >= 95) return "bg-danger";
  if (pct >= 80) return "bg-warning";
  return "bg-accent";
}

const memoryCount = computed(() => entries.value.filter((e) => (e.target ?? "memory") === "memory").length);
const userCount = computed(() => entries.value.filter((e) => e.target === "user").length);

const filteredEntries = computed(() => {
  if (targetFilter.value === "all") return entries.value;
  return entries.value.filter((e) => (e.target ?? "memory") === targetFilter.value);
});

function targetLabel(target?: string): string {
  return target === "user" ? "个人偏好" : "助理笔记";
}

function sourceLabel(source?: string): string {
  if (source === "assistant") return "AI 写入";
  return "手动添加";
}

function pendingActionLabel(action: string): string {
  if (action === "remove" || action === "delete") return "删除";
  if (action === "replace" || action === "update") return "更新";
  return "新增";
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

async function loadMemory() {
  loading.value = true;
  error.value = null;
  try {
    overview.value = await api.get<MemoryOverview>("/users/me/memory");
  } catch (e: any) {
    error.value = extractError(e, "加载长期记忆失败");
  } finally {
    loading.value = false;
  }
}

function onToggleMemory() {
  if (settingsSaving.value) return;
  feedback.value = null;
  error.value = null;
  if (!memoryEnabled.value) {
    void enableMemory();
  } else {
    void disableMemory();
  }
}

async function enableMemory() {
  settingsSaving.value = true;
  error.value = null;
  feedback.value = null;
  try {
    const res = await api.put<MemoryOverview>("/users/me/memory/settings", {
      enabled: true,
    });
    if (res && Array.isArray(res.entries)) {
      overview.value = res;
    } else {
      await loadMemory();
    }
    await auth.refreshUser();
    feedback.value = "已开启长期记忆功能";
  } catch (e: any) {
    error.value = extractError(e, "开启长期记忆失败");
  } finally {
    settingsSaving.value = false;
  }
}

async function disableMemory() {
  settingsSaving.value = true;
  error.value = null;
  feedback.value = null;
  try {
    const res = await api.put<MemoryOverview>("/users/me/memory/settings", {
      enabled: false,
    });
    if (res && Array.isArray(res.entries)) {
      overview.value = res;
    } else {
      await loadMemory();
    }
    await auth.refreshUser();
    feedback.value = "已关闭长期记忆（已有条目仍保留，可随时重新开启或清空）";
  } catch (e: any) {
    error.value = extractError(e, "关闭长期记忆失败");
  } finally {
    settingsSaving.value = false;
  }
}

async function onToggleRequireConfirm() {
  if (settingsSaving.value) return;
  settingsSaving.value = true;
  error.value = null;
  feedback.value = null;
  const nextVal = !requireConfirm.value;
  try {
    const res = await api.put<MemoryOverview>("/users/me/memory/settings", {
      require_confirm: nextVal,
    });
    if (res && Array.isArray(res.entries)) {
      overview.value = res;
    } else {
      await loadMemory();
    }
    await auth.refreshUser();
    feedback.value = nextVal ? "已开启写入前确认" : "已关闭写入前确认，AI 将直接写入记忆";
  } catch (e: any) {
    error.value = extractError(e, "更新确认偏好失败");
  } finally {
    settingsSaving.value = false;
  }
}

function startPendingEdit(item: MemoryPendingItem) {
  pendingEditId.value = item.id;
  pendingEditContent.value = item.content;
}

function cancelPendingEdit() {
  pendingEditId.value = null;
  pendingEditContent.value = "";
}

async function resolvePending(item: MemoryPendingItem, action: "approve" | "reject") {
  resolvingPendingId.value = item.id;
  error.value = null;
  feedback.value = null;
  try {
    const isEditingThis = pendingEditId.value === item.id;
    const isRemove = item.action === "remove" || item.action === "delete";
    const body: { action: "approve" | "reject"; content?: string } = { action };
    if (action === "approve" && isEditingThis && !isRemove) {
      const cleaned = pendingEditContent.value.trim();
      if (!cleaned) {
        error.value = "记忆内容不能为空";
        resolvingPendingId.value = null;
        return;
      }
      body.content = cleaned;
    }
    await api.post(`/users/me/memory/pending/${encodeURIComponent(item.id)}`, body);
    if (isEditingThis) cancelPendingEdit();
    await loadMemory();
    feedback.value = action === "approve" ? "已批准并写入长期记忆" : "已拒绝该记忆变更请求";
  } catch (e: any) {
    error.value = extractError(e, "处理待确认记忆失败");
  } finally {
    resolvingPendingId.value = null;
  }
}

function openAddForm() {
  addFormOpen.value = true;
  addError.value = null;
  newTarget.value = targetFilter.value === "user" ? "user" : "memory";
  newContent.value = "";
}

async function submitNewEntry() {
  addError.value = null;
  const cleaned = newContent.value.trim();
  if (!cleaned) {
    addError.value = "请输入要记录的内容";
    return;
  }
  addingEntry.value = true;
  feedback.value = null;
  try {
    await api.post("/users/me/memory/entries", {
      target: newTarget.value,
      content: cleaned,
    });
    addFormOpen.value = false;
    newContent.value = "";
    await loadMemory();
    feedback.value = "已添加新记忆条目";
  } catch (e: any) {
    addError.value = extractError(e, "添加记忆失败");
  } finally {
    addingEntry.value = false;
  }
}

function startEdit(entry: MemoryEntry) {
  editingId.value = entry.id;
  editTarget.value = entry.target === "user" ? "user" : "memory";
  editContent.value = entry.content;
  error.value = null;
}

function cancelEdit() {
  editingId.value = null;
  editContent.value = "";
}

async function saveEdit(entry: MemoryEntry) {
  const cleaned = editContent.value.trim();
  if (!cleaned) {
    error.value = "记忆内容不能为空";
    return;
  }
  savingEdit.value = true;
  error.value = null;
  feedback.value = null;
  try {
    await api.patch(`/users/me/memory/entries/${encodeURIComponent(entry.id)}`, {
      content: cleaned,
      target: editTarget.value,
    });
    cancelEdit();
    await loadMemory();
    feedback.value = "已更新记忆条目";
  } catch (e: any) {
    error.value = extractError(e, "更新记忆失败");
  } finally {
    savingEdit.value = false;
  }
}

async function deleteEntry(entry: MemoryEntry) {
  deletingId.value = entry.id;
  error.value = null;
  feedback.value = null;
  try {
    await api.delete(`/users/me/memory/entries/${encodeURIComponent(entry.id)}`);
    if (editingId.value === entry.id) cancelEdit();
    await loadMemory();
    feedback.value = "已删除记忆条目";
  } catch (e: any) {
    error.value = extractError(e, "删除记忆失败");
  } finally {
    deletingId.value = null;
  }
}

async function confirmClearAll() {
  clearingAll.value = true;
  modalError.value = null;
  feedback.value = null;
  try {
    await api.delete("/users/me/memory");
    clearModalOpen.value = false;
    cancelEdit();
    await loadMemory();
    feedback.value = "已清空全部长期记忆";
  } catch (e: any) {
    modalError.value = extractError(e, "清空记忆失败");
  } finally {
    clearingAll.value = false;
  }
}

onMounted(() => {
  void loadMemory();
});
</script>

<template>
  <div class="space-y-5">
    <!-- Top Switches & Quota Card -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-[15.5px] font-semibold text-fg">启用长期记忆</h2>
            <BaseBadge :tone="memoryEnabled ? 'green' : 'gray'">
              {{ memoryEnabled ? "已开启" : "未开启" }}
            </BaseBadge>
          </div>
          <p class="mt-1 text-[13px] leading-relaxed text-fg-muted">
            开启后，AI 助理可在独立隔离的 <code class="rounded bg-canvas px-1 py-0.5 text-[12px]">MEMORY.md</code> 与
            <code class="rounded bg-canvas px-1 py-0.5 text-[12px]">USER.md</code> 中跨对话记住你的工作背景与偏好。
          </p>
          <p v-if="memoryEnabled && overview?.memory_consented_at" class="mt-1 text-[12px] text-fg-faint">
            授权时间：{{ formatTime(overview.memory_consented_at) }}
          </p>
        </div>

        <button
          type="button"
          role="switch"
          :aria-checked="memoryEnabled"
          aria-label="启用长期记忆"
          :disabled="settingsSaving || loading"
          class="focus-ring relative mt-0.5 inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          :class="memoryEnabled ? 'bg-primary' : 'bg-line-strong'"
          @click="onToggleMemory"
        >
          <span
            class="h-6 w-6 rounded-full bg-canvas shadow-xs transition-transform"
            :class="memoryEnabled ? 'translate-x-5' : 'translate-x-0'"
          />
        </button>
      </div>

      <!-- Secondary Toggle: Require Confirm -->
      <div class="flex items-center justify-between gap-4 rounded-2xl bg-canvas/80 px-4 py-3 dark:bg-canvas/70">
        <div class="min-w-0">
          <p class="text-[14px] font-medium text-fg">AI 写入记忆前需要我确认</p>
          <p class="mt-0.5 text-[12.5px] text-fg-muted">
            默认关闭：AI 无需用户确认即可直接读取、写入和修改记忆；开启后，AI 提议新增或修改记忆时会先进入待确认队列。
          </p>
        </div>

        <button
          type="button"
          role="switch"
          :aria-checked="requireConfirm"
          aria-label="AI 写入记忆前需要我确认"
          :disabled="settingsSaving || loading"
          class="focus-ring relative inline-flex h-6.5 w-11 shrink-0 cursor-pointer items-center rounded-full p-0.5 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
          :class="requireConfirm ? 'bg-primary' : 'bg-line-strong'"
          @click="onToggleRequireConfirm"
        >
          <span
            class="h-5.5 w-5.5 rounded-full bg-canvas shadow-xs transition-transform"
            :class="requireConfirm ? 'translate-x-4.5' : 'translate-x-0'"
          />
        </button>
      </div>

      <!-- Character Usage Progress Bars -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div class="rounded-2xl bg-canvas/80 p-3.5 dark:bg-canvas/70">
          <div class="flex items-center justify-between gap-2 text-[12.5px]">
            <span class="font-medium text-fg">助理笔记 (MEMORY.md)</span>
            <span class="font-semibold tabular-nums text-fg-muted">
              {{ memoryCharCount }} / {{ memoryCharLimit }} 字符
            </span>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              class="h-full rounded-full transition-[width] duration-300"
              :class="barClass(memoryPercent)"
              :style="{ width: `${memoryPercent}%` }"
            />
          </div>
          <p class="mt-1.5 text-[11.5px] tabular-nums text-fg-faint">已用 {{ memoryPercent }}% · 共 {{ memoryCount }} 条</p>
        </div>

        <div class="rounded-2xl bg-canvas/80 p-3.5 dark:bg-canvas/70">
          <div class="flex items-center justify-between gap-2 text-[12.5px]">
            <span class="font-medium text-fg">个人偏好 (USER.md)</span>
            <span class="font-semibold tabular-nums text-fg-muted">
              {{ userCharCount }} / {{ userCharLimit }} 字符
            </span>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
            <div
              class="h-full rounded-full transition-[width] duration-300"
              :class="barClass(userPercent)"
              :style="{ width: `${userPercent}%` }"
            />
          </div>
          <p class="mt-1.5 text-[11.5px] tabular-nums text-fg-faint">已用 {{ userPercent }}% · 共 {{ userCount }} 条</p>
        </div>
      </div>
    </section>

    <FormError :message="error" />
    <div
      v-if="feedback"
      role="status"
      aria-live="polite"
      class="rounded-2xl bg-success-weak px-4 py-2.5 text-[13px] text-success"
    >
      {{ feedback }}
    </div>

    <!-- Pending Proposals -->
    <section
      v-if="pending.length > 0"
      class="space-y-3 rounded-[24px] bg-sidebar p-5 ring-1 ring-warning/35 sm:p-6 dark:bg-surface"
    >
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <h2 class="text-[15.5px] font-semibold text-fg">待确认的记忆提议</h2>
          <BaseBadge tone="amber">{{ pending.length }} 条待处理</BaseBadge>
        </div>
      </div>

      <div class="space-y-2.5">
        <article
          v-for="item in pending"
          :key="item.id"
          class="rounded-2xl bg-canvas p-4"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <BaseBadge :tone="item.target === 'user' ? 'brand' : 'gray'">
                {{ targetLabel(item.target) }}
              </BaseBadge>
              <BaseBadge
                :tone="item.action === 'remove' || item.action === 'delete' ? 'red' : item.action === 'replace' || item.action === 'update' ? 'amber' : 'green'"
              >
                {{ pendingActionLabel(item.action) }}
              </BaseBadge>
              <span v-if="item.created_at" class="text-[11.5px] text-fg-faint">
                {{ formatTime(item.created_at) }}
              </span>
            </div>

            <div class="flex items-center gap-1.5">
              <BaseButton
                v-if="item.action !== 'remove' && item.action !== 'delete' && pendingEditId !== item.id"
                variant="ghost"
                size="sm"
                rounded="full"
                :disabled="resolvingPendingId === item.id"
                @click="startPendingEdit(item)"
              >
                编辑内容
              </BaseButton>
              <BaseButton
                variant="soft"
                size="sm"
                rounded="full"
                :disabled="resolvingPendingId === item.id"
                @click="resolvePending(item, 'reject')"
              >
                拒绝
              </BaseButton>
              <BaseButton
                size="sm"
                rounded="full"
                :loading="resolvingPendingId === item.id"
                @click="resolvePending(item, 'approve')"
              >
                {{ pendingEditId === item.id ? "保存并批准" : "批准写入" }}
              </BaseButton>
            </div>
          </div>

          <div
            v-if="item.old_content"
            class="mt-2.5 rounded-xl bg-surface/80 px-3 py-2 text-[12.5px] text-fg-faint line-through"
          >
            {{ item.old_content }}
          </div>

          <div v-if="pendingEditId === item.id" class="mt-2.5 space-y-2">
            <textarea
              v-model="pendingEditContent"
              rows="3"
              maxlength="2000"
              aria-label="编辑待批准的记忆内容"
              class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3 py-2 text-[13.5px] leading-relaxed text-fg"
            />
            <div class="flex justify-end">
              <BaseButton variant="ghost" size="sm" rounded="full" @click="cancelPendingEdit">取消编辑</BaseButton>
            </div>
          </div>
          <p v-else class="mt-2.5 whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg">
            {{ item.content }}
          </p>
        </article>
      </div>
    </section>

    <!-- Entries Section -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="text-[15.5px] font-semibold text-fg">记忆条目</h2>
          <BaseBadge tone="gray">{{ entries.length }} 条</BaseBadge>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <BaseButton size="sm" rounded="full" @click="openAddForm">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
              <path stroke-linecap="round" d="M12 5v14M5 12h14" />
            </svg>
            <span>新增记忆</span>
          </BaseButton>
          <BaseButton
            variant="ghost"
            size="sm"
            rounded="full"
            class="text-danger hover:bg-danger-weak hover:text-danger"
            :disabled="loading || entries.length === 0"
            @click="modalError = null; clearModalOpen = true"
          >
            清空全部记忆
          </BaseButton>
        </div>
      </div>

      <!-- Filter Tabs -->
      <div class="flex flex-wrap items-center gap-1.5">
        <button
          v-for="tab in [
            { value: 'all', label: `全部 (${entries.length})` },
            { value: 'memory', label: `助理笔记 (${memoryCount})` },
            { value: 'user', label: `个人偏好 (${userCount})` },
          ] as const"
          :key="tab.value"
          type="button"
          class="focus-ring rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors"
          :class="
            targetFilter === tab.value
              ? 'bg-primary text-primary-fg'
              : 'bg-canvas text-fg-muted hover:bg-hover hover:text-fg'
          "
          @click="targetFilter = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>

      <!-- Add New Entry Form -->
      <form
        v-if="addFormOpen"
        class="space-y-3 rounded-2xl bg-canvas p-4"
        @submit.prevent="submitNewEntry"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="text-[13.5px] font-semibold text-fg">新增一条长期记忆</span>
          <div class="flex items-center gap-1.5">
            <button
              type="button"
              class="focus-ring rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors"
              :class="newTarget === 'memory' ? 'bg-primary text-primary-fg' : 'bg-surface text-fg-muted hover:text-fg'"
              @click="newTarget = 'memory'"
            >
              助理笔记 (MEMORY.md)
            </button>
            <button
              type="button"
              class="focus-ring rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors"
              :class="newTarget === 'user' ? 'bg-primary text-primary-fg' : 'bg-surface text-fg-muted hover:text-fg'"
              @click="newTarget = 'user'"
            >
              个人偏好 (USER.md)
            </button>
          </div>
        </div>

        <textarea
          v-model="newContent"
          rows="3"
          maxlength="2000"
          placeholder="例如：我在编写 Python 后端时偏好使用 FastAPI 与 SQLAlchemy 2.0 异步风格，请尽量给出完整类型注解。"
          class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3.5 py-2.5 text-[13.5px] leading-relaxed text-fg placeholder:text-fg-faint hover:border-line-strong"
        />

        <FormError :message="addError" />

        <div class="flex items-center justify-between gap-2">
          <span class="text-[11.5px] tabular-nums text-fg-faint">{{ newContent.trim().length }} / 2000 字符</span>
          <div class="flex items-center gap-2">
            <BaseButton type="button" variant="soft" size="sm" rounded="full" :disabled="addingEntry" @click="addFormOpen = false">
              取消
            </BaseButton>
            <BaseButton type="submit" size="sm" rounded="full" :loading="addingEntry">
              保存条目
            </BaseButton>
          </div>
        </div>
      </form>

      <!-- Loading / Empty / List -->
      <div v-if="loading && !overview" class="flex items-center justify-center gap-2 py-10 text-[13.5px] text-fg-muted">
        <Spinner :size="18" />
        <span>正在加载长期记忆…</span>
      </div>

      <div
        v-else-if="!filteredEntries.length"
        class="rounded-2xl border border-dashed border-line px-5 py-8 text-center text-[13px] text-fg-muted"
      >
        {{ entries.length ? "当前分类下暂无记忆条目。" : "暂无长期记忆条目。可在对话中自动记录，或点击右上角「新增记忆」手动添加。" }}
      </div>

      <div v-else class="space-y-2.5">
        <article
          v-for="entry in filteredEntries"
          :key="entry.id"
          class="rounded-2xl bg-canvas p-4 transition-colors"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <BaseBadge :tone="entry.target === 'user' ? 'brand' : 'gray'">
                {{ targetLabel(entry.target) }}
              </BaseBadge>
              <BaseBadge tone="gray">{{ sourceLabel(entry.source) }}</BaseBadge>
              <span class="text-[11.5px] tabular-nums text-fg-faint">{{ entry.content.length }} 字符</span>
              <span v-if="entry.updated_at || entry.created_at" class="text-[11.5px] text-fg-faint">
                · {{ formatTime(entry.updated_at ?? entry.created_at) }}
              </span>
            </div>

            <div v-if="editingId !== entry.id" class="flex items-center gap-1">
              <BaseButton
                variant="ghost"
                size="sm"
                rounded="full"
                :disabled="deletingId === entry.id"
                @click="startEdit(entry)"
              >
                编辑
              </BaseButton>
              <BaseButton
                variant="ghost"
                size="sm"
                rounded="full"
                class="text-danger hover:bg-danger-weak hover:text-danger"
                :loading="deletingId === entry.id"
                @click="deleteEntry(entry)"
              >
                删除
              </BaseButton>
            </div>
          </div>

          <div v-if="editingId === entry.id" class="mt-3 space-y-2.5">
            <div class="flex items-center gap-1.5">
              <button
                type="button"
                class="focus-ring rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors"
                :class="editTarget === 'memory' ? 'bg-primary text-primary-fg' : 'bg-surface text-fg-muted hover:text-fg'"
                @click="editTarget = 'memory'"
              >
                助理笔记
              </button>
              <button
                type="button"
                class="focus-ring rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors"
                :class="editTarget === 'user' ? 'bg-primary text-primary-fg' : 'bg-surface text-fg-muted hover:text-fg'"
                @click="editTarget = 'user'"
              >
                个人偏好
              </button>
            </div>
            <textarea
              v-model="editContent"
              rows="3"
              maxlength="2000"
              aria-label="编辑记忆内容"
              class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3.5 py-2.5 text-[13.5px] leading-relaxed text-fg"
            />
            <div class="flex justify-end gap-2">
              <BaseButton variant="soft" size="sm" rounded="full" :disabled="savingEdit" @click="cancelEdit">
                取消
              </BaseButton>
              <BaseButton size="sm" rounded="full" :loading="savingEdit" @click="saveEdit(entry)">
                保存修改
              </BaseButton>
            </div>
          </div>

          <p v-else class="mt-2.5 whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg">
            {{ entry.content }}
          </p>
        </article>
      </div>
    </section>

    <!-- Clear All Confirmation Modal -->
    <BaseModal
      :open="clearModalOpen"
      title="清空全部记忆"
      @close="clearModalOpen = false"
    >
      <div class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          确定要清空全部 <strong class="font-medium text-fg">{{ entries.length }}</strong> 条长期记忆（包括
          <code class="rounded bg-surface px-1 py-0.5 text-[12px]">MEMORY.md</code> 与
          <code class="rounded bg-surface px-1 py-0.5 text-[12px]">USER.md</code>）吗？此操作不可撤销。
        </p>
        <FormError :message="modalError" />
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="clearingAll" @click="clearModalOpen = false">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="clearingAll" @click="confirmClearAll">
          确认清空
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
