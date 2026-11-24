<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import type {
  MemoryCollection,
  MemoryEntry,
  MemoryOverview,
  MemoryPendingItem,
  MemorySearchHit,
  MemorySearchResponse,
} from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import FormError from "../ui/FormError.vue";
import Spinner from "../ui/Spinner.vue";
import AppIcon from "../ui/AppIcon.vue";

const auth = useAuthStore();

const overview = ref<MemoryOverview | null>(null);
const loading = ref(true);
const error = ref<string | null>(null);
const feedback = ref<string | null>(null);

const settingsSaving = ref(false);
const modalError = ref<string | null>(null);

// Active collection filter ("all" or collection slug)
const activeSlug = ref<string>("all");

// Collection create / edit modal
const collectionModalOpen = ref(false);
const editingCollection = ref<MemoryCollection | null>(null);
const colName = ref("");
const colSlug = ref("");
const colDescription = ref("");
const colCharLimit = ref(12000);
const savingCollection = ref(false);
const togglingCollectionId = ref<string | null>(null);

// Delete collection confirmation modal
const deleteColTarget = ref<MemoryCollection | null>(null);
const deletingCollection = ref(false);

// RAG Search state
const searchQuery = ref("");
const searching = ref(false);
const searchResults = ref<MemorySearchHit[] | null>(null);

// Add entry state
const addFormOpen = ref(false);
const newTarget = ref<string>("memory");
const newTitle = ref("");
const newTagsText = ref("");
const newContent = ref("");
const addingEntry = ref(false);
const addError = ref<string | null>(null);

// Inline edit entry state
const editingId = ref<string | null>(null);
const editTarget = ref<string>("memory");
const editTitle = ref("");
const editTagsText = ref("");
const editContent = ref("");
const savingEdit = ref(false);
const deletingId = ref<string | null>(null);
const pinningId = ref<string | null>(null);

async function togglePinEntry(entry: MemoryEntry) {
  if (pinningId.value) return;
  pinningId.value = entry.id;
  error.value = null;
  feedback.value = null;
  const nextPinned = !entry.is_pinned;
  try {
    overview.value = await api.patch<MemoryOverview>(`/users/me/memory/entries/${encodeURIComponent(entry.id)}`, {
      is_pinned: nextPinned,
      priority: nextPinned ? 1 : 2,
    });
    feedback.value = nextPinned
      ? "已置顶为 L0 常驻核心记忆（每轮对话自动遵循，不依赖 RAG 召回）"
      : "已取消常驻置顶（转为按需混合 RAG 检索）";
  } catch (e: any) {
    error.value = extractError(e, "切换常驻置顶失败");
  } finally {
    pinningId.value = null;
  }
}

// Pending proposals state
const pendingEditId = ref<string | null>(null);
const pendingEditContent = ref("");
const resolvingPendingId = ref<string | null>(null);

// Clear confirmation modal
const clearModalOpen = ref(false);
const clearingAll = ref(false);

function extractError(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

function parseTags(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 10);
}

const memoryEnabled = computed(() => overview.value?.memory_enabled ?? true);
const requireConfirm = computed(() => overview.value?.memory_require_confirm ?? false);
const collections = computed<MemoryCollection[]>(() => overview.value?.collections ?? []);
const entries = computed<MemoryEntry[]>(() => overview.value?.entries ?? []);
const pending = computed<MemoryPendingItem[]>(() => overview.value?.pending ?? []);

const totalCharCount = computed(() => overview.value?.total_char_count ?? overview.value?.char_count ?? 0);
const totalCharLimit = computed(() => overview.value?.total_char_limit ?? 200000);
const collectionLimit = computed(() => overview.value?.collection_limit ?? 50);

const totalPercent = computed(() =>
  totalCharLimit.value > 0 ? Math.min(100, Math.round((totalCharCount.value / totalCharLimit.value) * 100)) : 0,
);

const activeCollection = computed<MemoryCollection | null>(() =>
  activeSlug.value === "all" ? null : (collections.value.find((c) => c.slug === activeSlug.value) ?? null),
);

const filteredEntries = computed(() => {
  if (activeSlug.value === "all") return entries.value;
  return entries.value.filter((e) => (e.target ?? "memory") === activeSlug.value);
});

function barClass(pct: number): string {
  if (pct >= 95) return "bg-danger";
  if (pct >= 80) return "bg-warning";
  return "bg-accent";
}

function collectionPercent(col: MemoryCollection): number {
  return col.char_limit > 0 ? Math.min(100, Math.round((col.char_count / col.char_limit) * 100)) : 0;
}

function collectionNameFor(target?: string, fallback?: string | null): string {
  if (fallback) return fallback;
  const slug = target || "memory";
  const found = collections.value.find((c) => c.slug === slug);
  if (found) return found.name;
  if (slug === "user") return "个人画像与偏好";
  if (slug === "projects") return "项目与工作";
  if (slug === "memory") return "通用笔记";
  return slug;
}

function sourceLabel(source?: string): string {
  if (source === "assistant" || source === "agent") return "AI 写入";
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
    if (activeSlug.value !== "all" && !collections.value.some((c) => c.slug === activeSlug.value)) {
      activeSlug.value = "all";
    }
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
    const res = await api.put<MemoryOverview>("/users/me/memory/settings", { enabled: true });
    overview.value = res;
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
    const res = await api.put<MemoryOverview>("/users/me/memory/settings", { enabled: false });
    overview.value = res;
    await auth.refreshUser();
    feedback.value = "已关闭长期记忆（已有记忆集与条目仍保留）";
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
    const res = await api.put<MemoryOverview>("/users/me/memory/settings", { require_confirm: nextVal });
    overview.value = res;
    await auth.refreshUser();
    feedback.value = nextVal ? "已开启写入前确认" : "已关闭写入前确认，AI 将直接读写和修改记忆集";
  } catch (e: any) {
    error.value = extractError(e, "更新确认偏好失败");
  } finally {
    settingsSaving.value = false;
  }
}

// --- Collections CRUD ---
function openCreateCollection() {
  editingCollection.value = null;
  colName.value = "";
  colSlug.value = "";
  colDescription.value = "";
  colCharLimit.value = 12000;
  modalError.value = null;
  collectionModalOpen.value = true;
}

function openEditCollection(col: MemoryCollection) {
  editingCollection.value = col;
  colName.value = col.name;
  colSlug.value = col.slug;
  colDescription.value = col.description || "";
  colCharLimit.value = col.char_limit || 12000;
  modalError.value = null;
  collectionModalOpen.value = true;
}

async function saveCollection() {
  const cleanedName = colName.value.trim();
  if (!cleanedName) {
    modalError.value = "请输入记忆集名称";
    return;
  }
  savingCollection.value = true;
  modalError.value = null;
  feedback.value = null;
  try {
    if (editingCollection.value) {
      overview.value = await api.patch<MemoryOverview>(
        `/users/me/memory/collections/${encodeURIComponent(editingCollection.value.id)}`,
        {
          name: cleanedName,
          description: colDescription.value.trim(),
          char_limit: Number(colCharLimit.value) || 12000,
        },
      );
      feedback.value = `已更新记忆集「${cleanedName}」`;
    } else {
      overview.value = await api.post<MemoryOverview>("/users/me/memory/collections", {
        name: cleanedName,
        slug: colSlug.value.trim() || undefined,
        description: colDescription.value.trim(),
        char_limit: Number(colCharLimit.value) || 12000,
      });
      feedback.value = `已新建记忆集「${cleanedName}」`;
    }
    collectionModalOpen.value = false;
  } catch (e: any) {
    modalError.value = extractError(e, "保存记忆集失败");
  } finally {
    savingCollection.value = false;
  }
}

async function toggleCollectionEnabled(col: MemoryCollection) {
  if (togglingCollectionId.value) return;
  togglingCollectionId.value = col.id;
  error.value = null;
  feedback.value = null;
  try {
    overview.value = await api.patch<MemoryOverview>(
      `/users/me/memory/collections/${encodeURIComponent(col.id)}`,
      { enabled: !col.enabled },
    );
    feedback.value = !col.enabled ? `已启用记忆集「${col.name}」` : `已暂停记忆集「${col.name}」的 RAG 召回`;
  } catch (e: any) {
    error.value = extractError(e, "切换记忆集状态失败");
  } finally {
    togglingCollectionId.value = null;
  }
}

async function confirmDeleteCollection() {
  if (!deleteColTarget.value) return;
  deletingCollection.value = true;
  modalError.value = null;
  feedback.value = null;
  const targetCol = deleteColTarget.value;
  try {
    overview.value = await api.delete<MemoryOverview>(
      `/users/me/memory/collections/${encodeURIComponent(targetCol.id)}`,
    );
    if (activeSlug.value === targetCol.slug) {
      activeSlug.value = "all";
    }
    deleteColTarget.value = null;
    feedback.value = `已删除记忆集「${targetCol.name}」`;
  } catch (e: any) {
    modalError.value = extractError(e, "删除记忆集失败");
  } finally {
    deletingCollection.value = false;
  }
}

// --- RAG Search ---
async function runRagSearch() {
  const q = searchQuery.value.trim();
  if (!q) {
    searchResults.value = null;
    return;
  }
  searching.value = true;
  error.value = null;
  try {
    const res = await api.post<MemorySearchResponse>("/users/me/memory/search", {
      query: q,
      collection: activeSlug.value === "all" ? null : activeSlug.value,
      limit: 20,
    });
    searchResults.value = res.results ?? [];
  } catch (e: any) {
    error.value = extractError(e, "RAG 语义检索失败");
  } finally {
    searching.value = false;
  }
}

function selectCollection(slug: string) {
  activeSlug.value = slug;
  if (searchQuery.value.trim()) {
    void runRagSearch();
  }
}

function onSearchInput() {
  if (!searchQuery.value.trim()) {
    searchResults.value = null;
  }
}

function clearSearch() {
  searchQuery.value = "";
  searchResults.value = null;
}

// --- Pending Proposals ---
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
    overview.value = await api.post<MemoryOverview>(`/users/me/memory/pending/${encodeURIComponent(item.id)}`, body);
    if (isEditingThis) cancelPendingEdit();
    feedback.value = action === "approve" ? "已批准并写入长期记忆" : "已拒绝该记忆变更请求";
  } catch (e: any) {
    error.value = extractError(e, "处理待确认记忆失败");
  } finally {
    resolvingPendingId.value = null;
  }
}

// --- Entries CRUD ---
function openAddForm() {
  addFormOpen.value = true;
  addError.value = null;
  newTarget.value = activeSlug.value !== "all" ? activeSlug.value : (collections.value[0]?.slug ?? "memory");
  newTitle.value = "";
  newTagsText.value = "";
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
    overview.value = await api.post<MemoryOverview>("/users/me/memory/entries", {
      target: newTarget.value,
      title: newTitle.value.trim(),
      tags: parseTags(newTagsText.value),
      content: cleaned,
    });
    addFormOpen.value = false;
    newTitle.value = "";
    newTagsText.value = "";
    newContent.value = "";
    feedback.value = "已添加新记忆条目";
  } catch (e: any) {
    addError.value = extractError(e, "添加记忆失败");
  } finally {
    addingEntry.value = false;
  }
}

function startEdit(entry: MemoryEntry) {
  editingId.value = entry.id;
  editTarget.value = entry.target || "memory";
  editTitle.value = entry.title || "";
  editTagsText.value = (entry.tags ?? []).join(", ");
  editContent.value = entry.content;
  error.value = null;
}

function cancelEdit() {
  editingId.value = null;
  editTitle.value = "";
  editTagsText.value = "";
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
    overview.value = await api.patch<MemoryOverview>(`/users/me/memory/entries/${encodeURIComponent(entry.id)}`, {
      content: cleaned,
      target: editTarget.value,
      title: editTitle.value.trim(),
      tags: parseTags(editTagsText.value),
    });
    cancelEdit();
    if (searchResults.value !== null) {
      await runRagSearch();
    }
    feedback.value = "已更新记忆条目";
  } catch (e: any) {
    error.value = extractError(e, "更新记忆失败");
  } finally {
    savingEdit.value = false;
  }
}

async function deleteEntry(entryId: string) {
  deletingId.value = entryId;
  error.value = null;
  feedback.value = null;
  try {
    overview.value = await api.delete<MemoryOverview>(`/users/me/memory/entries/${encodeURIComponent(entryId)}`);
    if (editingId.value === entryId) cancelEdit();
    if (searchResults.value !== null) {
      searchResults.value = searchResults.value.filter((h) => h.id !== entryId);
    }
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
    const qs = activeCollection.value
      ? `?collection_id=${encodeURIComponent(activeCollection.value.id)}`
      : "";
    overview.value = await api.delete<MemoryOverview>(`/users/me/memory${qs}`);
    clearModalOpen.value = false;
    cancelEdit();
    searchResults.value = null;
    feedback.value = activeCollection.value
      ? `已清空「${activeCollection.value.name}」中的全部条目`
      : "已清空全部长期记忆";
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
    <!-- Top Switches & Global Quota Card -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-[15.5px] font-semibold text-fg">启用长期记忆集</h2>
            <BaseBadge :tone="memoryEnabled ? 'green' : 'gray'">
              {{ memoryEnabled ? "已开启" : "未开启" }}
            </BaseBadge>
          </div>
          <p class="mt-1 text-[13px] leading-relaxed text-fg-muted">
            开启后，AI 助理将通过轻量目录索引与混合 RAG（向量 + 全文 + 模糊重排）跨对话管理你的多个主题记忆集。
          </p>
        </div>

        <button
          type="button"
          role="switch"
          :aria-checked="memoryEnabled"
          aria-label="启用长期记忆集"
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
            默认关闭：AI 无需用户确认即可直接读取、写入、修改记忆并新建记忆集；开启后将先进入待确认队列。
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

      <!-- Global Capacity Bar -->
      <div class="rounded-2xl bg-canvas/80 p-3.5 dark:bg-canvas/70">
        <div class="flex flex-wrap items-center justify-between gap-2 text-[12.5px]">
          <span class="font-medium text-fg">
            记忆集总容量 · {{ collections.length }} / {{ collectionLimit }} 个记忆集 · 共 {{ entries.length }} 条
            <span class="ml-1.5 rounded-full bg-accent-weak px-2 py-0.5 text-[11px] font-medium text-accent">
              L0 常驻核心 {{ overview?.pinned_count ?? entries.filter((e) => e.is_pinned).length }} / {{ overview?.pinned_limit ?? 10 }}
            </span>
          </span>
          <span class="font-semibold tabular-nums text-fg-muted">
            {{ totalCharCount.toLocaleString() }} / {{ totalCharLimit.toLocaleString() }} 字符
          </span>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
          <div
            class="h-full rounded-full transition-[width] duration-300"
            :class="barClass(totalPercent)"
            :style="{ width: `${totalPercent}%` }"
          />
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

    <!-- Collections Management Section -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <h2 class="text-[15.5px] font-semibold text-fg">记忆集目录</h2>
          <BaseBadge tone="gray">{{ collections.length }} 个</BaseBadge>
        </div>
        <BaseButton size="sm" rounded="full" :disabled="loading" @click="openCreateCollection">
          <AppIcon name="plus" class="h-3.5 w-3.5" :stroke-width="2.1" />
          <span>新建记忆集</span>
        </BaseButton>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <!-- All Collections Card -->
        <button
          type="button"
          class="focus-ring flex flex-col justify-between rounded-2xl p-3.5 text-left transition-colors"
          :class="
            activeSlug === 'all'
              ? 'bg-primary text-primary-fg ring-1 ring-primary'
              : 'bg-canvas/80 text-fg hover:bg-canvas dark:bg-canvas/70'
          "
          @click="selectCollection('all')"
        >
          <div>
            <div class="flex items-center justify-between gap-2">
              <span class="text-[13.5px] font-semibold">全部记忆集</span>
              <span class="text-[11.5px] tabular-nums opacity-80">{{ entries.length }} 条</span>
            </div>
            <p class="mt-1 text-[12px] opacity-75">跨全部记忆集浏览与检索条目</p>
          </div>
          <p class="mt-3 text-[11.5px] tabular-nums opacity-75">{{ collections.length }} 个记忆集</p>
        </button>

        <!-- Individual Collection Cards -->
        <div
          v-for="col in collections"
          :key="col.id"
          class="flex flex-col justify-between rounded-2xl p-3.5 transition-colors"
          :class="
            activeSlug === col.slug
              ? 'bg-canvas ring-2 ring-primary'
              : 'bg-canvas/80 hover:bg-canvas dark:bg-canvas/70'
          "
        >
          <div class="cursor-pointer" @click="selectCollection(col.slug)">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="truncate text-[13.5px] font-semibold text-fg">{{ col.name }}</span>
                  <BaseBadge v-if="col.kind === 'system'" tone="gray">预置</BaseBadge>
                  <BaseBadge v-if="!col.enabled" tone="amber">已暂停</BaseBadge>
                </div>
                <p class="mt-0.5 truncate font-mono text-[11px] text-fg-faint">{{ col.slug }}</p>
              </div>
              <span class="shrink-0 text-[11.5px] font-medium tabular-nums text-fg-muted">
                {{ col.entry_count }} 条
              </span>
            </div>

            <p v-if="col.description" class="mt-1.5 line-clamp-2 text-[12px] leading-relaxed text-fg-muted">
              {{ col.description }}
            </p>

            <div class="mt-2.5 h-1 overflow-hidden rounded-full bg-surface">
              <div
                class="h-full rounded-full transition-[width] duration-300"
                :class="barClass(collectionPercent(col))"
                :style="{ width: `${collectionPercent(col)}%` }"
              />
            </div>
          </div>

          <div class="mt-2.5 flex items-center justify-between gap-2 border-t border-line/60 pt-2">
            <span class="text-[11px] tabular-nums text-fg-faint">
              {{ col.char_count }} / {{ col.char_limit }} 字
            </span>
            <div class="flex items-center gap-1">
              <button
                type="button"
                class="focus-ring rounded-full px-2 py-0.5 text-[11.5px] font-medium transition-colors"
                :class="col.enabled ? 'text-fg-muted hover:bg-hover hover:text-fg' : 'bg-accent-weak text-accent'"
                :disabled="togglingCollectionId === col.id"
                @click.stop="toggleCollectionEnabled(col)"
              >
                {{ col.enabled ? "暂停" : "启用" }}
              </button>
              <button
                type="button"
                class="focus-ring rounded-full px-2 py-0.5 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                @click.stop="openEditCollection(col)"
              >
                编辑
              </button>
              <button
                v-if="col.kind !== 'system'"
                type="button"
                class="focus-ring rounded-full px-2 py-0.5 text-[11.5px] font-medium text-danger transition-colors hover:bg-danger-weak"
                @click.stop="modalError = null; deleteColTarget = col"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

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
              <BaseBadge tone="brand">{{ collectionNameFor(item.target) }}</BaseBadge>
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
              maxlength="4000"
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

    <!-- Entries & Hybrid RAG Search Section -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="text-[15.5px] font-semibold text-fg">
            {{ activeCollection ? `「${activeCollection.name}」条目` : "全部记忆条目" }}
          </h2>
          <BaseBadge tone="gray">
            {{ searchResults !== null ? `检索命中 ${searchResults.length} 条` : `${filteredEntries.length} 条` }}
          </BaseBadge>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <BaseButton size="sm" rounded="full" @click="openAddForm">
            <AppIcon name="plus" class="h-3.5 w-3.5" :stroke-width="2.1" />
            <span>新增记忆</span>
          </BaseButton>
          <BaseButton
            variant="ghost"
            size="sm"
            rounded="full"
            class="text-danger hover:bg-danger-weak hover:text-danger"
            :disabled="loading || filteredEntries.length === 0"
            @click="modalError = null; clearModalOpen = true"
          >
            {{ activeCollection ? "清空当前集" : "清空全部记忆" }}
          </BaseButton>
        </div>
      </div>

      <!-- RAG Semantic Search Bar -->
      <form class="flex items-center gap-2" @submit.prevent="runRagSearch">
        <div class="relative flex-1">
          <input
            v-model="searchQuery"
            type="search"
            placeholder="混合 RAG 语义 / 关键词检索记忆（支持跨记忆集召回）…"
            class="focus-ring w-full rounded-xl border border-line bg-canvas px-3.5 py-2 text-[13.5px] text-fg placeholder:text-fg-faint hover:border-line-strong"
            @input="onSearchInput"
          />
        </div>
        <BaseButton type="submit" size="sm" variant="secondary" rounded="full" :loading="searching">
          检索
        </BaseButton>
        <BaseButton v-if="searchResults !== null" type="button" size="sm" variant="ghost" rounded="full" @click="clearSearch">
          清除
        </BaseButton>
      </form>

      <!-- Add New Entry Form -->
      <form
        v-if="addFormOpen"
        class="space-y-3 rounded-2xl bg-canvas p-4"
        @submit.prevent="submitNewEntry"
      >
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="text-[13.5px] font-semibold text-fg">新增一条长期记忆</span>
          <select
            v-model="newTarget"
            aria-label="选择目标记忆集"
            class="focus-ring rounded-xl border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-fg"
          >
            <option v-for="col in collections" :key="col.id" :value="col.slug">
              {{ col.name }} ({{ col.slug }})
            </option>
          </select>
        </div>

        <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          <input
            v-model="newTitle"
            type="text"
            maxlength="120"
            placeholder="可选标题（如：后端技术栈偏好）"
            class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint"
          />
          <input
            v-model="newTagsText"
            type="text"
            maxlength="160"
            placeholder="可选标签，逗号分隔（如：python, fastapi）"
            class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint"
          />
        </div>

        <textarea
          v-model="newContent"
          rows="3"
          maxlength="4000"
          placeholder="例如：我在编写 Python 后端时偏好使用 FastAPI 与 SQLAlchemy 2.0 异步风格，请尽量给出完整类型注解。"
          class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3.5 py-2.5 text-[13.5px] leading-relaxed text-fg placeholder:text-fg-faint hover:border-line-strong"
        />

        <FormError :message="addError" />

        <div class="flex items-center justify-between gap-2">
          <span class="text-[11.5px] tabular-nums text-fg-faint">{{ newContent.trim().length }} / 4000 字符</span>
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

      <!-- RAG Search Results View -->
      <div v-if="searchResults !== null" class="space-y-2.5">
        <div
          v-if="searchResults.length === 0"
          class="rounded-2xl border border-dashed border-line px-5 py-8 text-center text-[13px] text-fg-muted"
        >
          未检索到与「{{ searchQuery }}」相关的记忆条目。
        </div>
        <article
          v-for="hit in searchResults"
          :key="hit.id"
          class="rounded-2xl bg-canvas p-4 ring-1 ring-accent/25"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <BaseBadge tone="brand">{{ hit.collection_name || collectionNameFor(hit.target) }}</BaseBadge>
              <BaseBadge tone="green">相关度 {{ hit.score.toFixed(4) }}</BaseBadge>
              <BaseBadge tone="gray">{{ sourceLabel(hit.source) }}</BaseBadge>
            </div>
            <BaseButton
              variant="ghost"
              size="sm"
              rounded="full"
              class="text-danger hover:bg-danger-weak hover:text-danger"
              :loading="deletingId === hit.id"
              @click="deleteEntry(hit.id)"
            >
              删除
            </BaseButton>
          </div>
          <p v-if="hit.title" class="mt-2 text-[13.5px] font-semibold text-fg">{{ hit.title }}</p>
          <p class="mt-1.5 whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg">
            {{ hit.content }}
          </p>
          <div v-if="hit.tags?.length" class="mt-2 flex flex-wrap gap-1">
            <span
              v-for="tag in hit.tags"
              :key="tag"
              class="rounded-full bg-surface px-2 py-0.5 text-[11px] text-fg-muted"
            >
              #{{ tag }}
            </span>
          </div>
        </article>
      </div>

      <!-- Loading / Empty / Normal List -->
      <div v-else-if="loading && !overview" class="flex items-center justify-center gap-2 py-10 text-[13.5px] text-fg-muted">
        <Spinner :size="18" />
        <span>正在加载长期记忆…</span>
      </div>

      <div
        v-else-if="!filteredEntries.length"
        class="rounded-2xl border border-dashed border-line px-5 py-8 text-center text-[13px] text-fg-muted"
      >
        {{ entries.length ? "当前记忆集下暂无条目。" : "暂无长期记忆条目。可在对话中自动记录，或点击右上角「新增记忆」手动添加。" }}
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
                {{ collectionNameFor(entry.target, entry.collection_name) }}
              </BaseBadge>
              <BaseBadge v-if="entry.is_pinned" tone="brand">
                L0 常驻
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
                :class="entry.is_pinned ? 'bg-accent-weak/80 text-accent' : ''"
                :loading="pinningId === entry.id"
                :disabled="deletingId === entry.id"
                :title="entry.is_pinned ? '取消常驻核心（改为按需检索）' : '置顶为 L0 常驻核心记忆（每轮自动注入前缀）'"
                @click="togglePinEntry(entry)"
              >
                {{ entry.is_pinned ? "取消常驻" : "常驻核心" }}
              </BaseButton>
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
                @click="deleteEntry(entry.id)"
              >
                删除
              </BaseButton>
            </div>
          </div>

          <div v-if="editingId === entry.id" class="mt-3 space-y-2.5">
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <select
                v-model="editTarget"
                aria-label="目标记忆集"
                class="focus-ring rounded-xl border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-fg"
              >
                <option v-for="col in collections" :key="col.id" :value="col.slug">
                  {{ col.name }} ({{ col.slug }})
                </option>
              </select>
              <input
                v-model="editTitle"
                type="text"
                maxlength="120"
                placeholder="可选标题"
                class="focus-ring rounded-xl border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-fg"
              />
              <input
                v-model="editTagsText"
                type="text"
                maxlength="160"
                placeholder="标签（逗号分隔）"
                class="focus-ring rounded-xl border border-line bg-canvas px-3 py-1.5 text-[12.5px] text-fg"
              />
            </div>
            <textarea
              v-model="editContent"
              rows="3"
              maxlength="4000"
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

          <div v-else class="mt-2.5">
            <p v-if="entry.title" class="mb-1 text-[13.5px] font-semibold text-fg">{{ entry.title }}</p>
            <p class="whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg">
              {{ entry.content }}
            </p>
            <div v-if="entry.tags?.length" class="mt-2 flex flex-wrap gap-1">
              <span
                v-for="tag in entry.tags"
                :key="tag"
                class="rounded-full bg-surface px-2 py-0.5 text-[11px] text-fg-muted"
              >
                #{{ tag }}
              </span>
            </div>
          </div>
        </article>
      </div>
    </section>

    <!-- Create / Edit Collection Modal -->
    <BaseModal
      :open="collectionModalOpen"
      :title="editingCollection ? '编辑记忆集' : '新建记忆集'"
      width="30rem"
      @close="collectionModalOpen = false"
    >
      <div class="space-y-3">
        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">名称</label>
          <input
            v-model="colName"
            type="text"
            maxlength="80"
            placeholder="例如：Whitz 项目、阅读笔记、写作风格"
            class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13.5px] text-fg"
          />
        </div>
        <div v-if="!editingCollection">
          <label class="mb-1 block text-[12.5px] font-medium text-fg">标识 Slug（可选，留空自动生成）</label>
          <input
            v-model="colSlug"
            type="text"
            maxlength="64"
            placeholder="例如：project-whitz"
            class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 py-2 font-mono text-[13px] text-fg"
          />
        </div>
        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">简介（用于 AI 目录索引归类参考）</label>
          <textarea
            v-model="colDescription"
            rows="2"
            maxlength="300"
            placeholder="简述这个记忆集存放哪类信息，方便 AI 自动归类与检索"
            class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg"
          />
        </div>
        <div>
          <label class="mb-1 block text-[12.5px] font-medium text-fg">单集字符上限（2,000 ~ 50,000）</label>
          <input
            v-model.number="colCharLimit"
            type="number"
            min="2000"
            max="50000"
            step="1000"
            class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] tabular-nums text-fg"
          />
        </div>
        <FormError :message="modalError" />
      </div>

      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="savingCollection" @click="collectionModalOpen = false">
          取消
        </BaseButton>
        <BaseButton rounded="full" :loading="savingCollection" @click="saveCollection">
          保存
        </BaseButton>
      </template>
    </BaseModal>

    <!-- Delete Collection Confirmation Modal -->
    <BaseModal
      :open="Boolean(deleteColTarget)"
      title="删除记忆集"
      @close="deleteColTarget = null"
    >
      <div class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          确定要删除记忆集「<strong class="font-medium text-fg">{{ deleteColTarget?.name }}</strong>」及其包含的
          <strong class="font-medium text-fg">{{ deleteColTarget?.entry_count ?? 0 }}</strong> 条记忆吗？此操作不可撤销。
        </p>
        <FormError :message="modalError" />
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="deletingCollection" @click="deleteColTarget = null">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="deletingCollection" @click="confirmDeleteCollection">
          确认删除
        </BaseButton>
      </template>
    </BaseModal>

    <!-- Clear All / Collection Confirmation Modal -->
    <BaseModal
      :open="clearModalOpen"
      :title="activeCollection ? `清空「${activeCollection.name}」` : '清空全部记忆'"
      @close="clearModalOpen = false"
    >
      <div class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          <template v-if="activeCollection">
            确定要清空「<strong class="font-medium text-fg">{{ activeCollection.name }}</strong>」中的
            <strong class="font-medium text-fg">{{ filteredEntries.length }}</strong> 条记忆吗？此操作不可撤销。
          </template>
          <template v-else>
            确定要清空全部 <strong class="font-medium text-fg">{{ entries.length }}</strong> 条长期记忆吗？记忆集目录将保留，但所有条目会被永久删除。
          </template>
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
