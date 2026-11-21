<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "../../api/client";
import { ACCEPT_ATTR, categoryLabel, formatFileSize } from "../../lib/fileTypes";
import { useFilesStore } from "../../stores/files";
import type { LibraryFileItem } from "../../types";
import MarkdownRenderer from "../chat/MarkdownRenderer.vue";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import FormError from "../ui/FormError.vue";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  embedded?: boolean;
}>();

type CategoryFilter = "all" | "document" | "spreadsheet" | "code" | "image";
type SourceFilter = "all" | "user" | "assistant";

const PAGE_SIZE = 24;

const filesStore = useFilesStore();

const files = ref<LibraryFileItem[]>([]);
const totalCount = ref<number | null>(null);
const hasNextPage = ref(false);
const page = ref(1);
const loading = ref(true);
const error = ref<string | null>(null);
const feedback = ref<string | null>(null);

const searchInput = ref("");
const searchQuery = ref("");
const categoryFilter = ref<CategoryFilter>("all");
const sourceFilter = ref<SourceFilter>("all");

const brokenThumbs = ref<Record<string, boolean>>({});
const downloadingId = ref<string | null>(null);
const uploading = ref(false);
const uploadInputRef = ref<HTMLInputElement | null>(null);

// Preview modal state
const previewFile = ref<LibraryFileItem | null>(null);
const previewLoading = ref(false);
const previewError = ref<string | null>(null);
const previewUrl = ref<string | null>(null);
const previewText = ref<string | null>(null);
const previewMode = ref<"rendered" | "source">("rendered");

// Delete confirmation modal
const deleteTarget = ref<LibraryFileItem | null>(null);
const deleting = ref(false);
const deleteError = ref<string | null>(null);

let searchTimer: number | null = null;

function extractError(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

function isUrlNearExpiry(expiresAt?: string | null): boolean {
  if (!expiresAt) return false;
  const ms = new Date(expiresAt).getTime();
  if (Number.isNaN(ms)) return false;
  return ms - Date.now() < 30_000;
}

const TEXT_PREVIEW_EXTS = new Set([
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".tsv",
  ".json",
  ".jsonl",
  ".yaml",
  ".yml",
  ".xml",
  ".py",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
  ".vue",
  ".html",
  ".htm",
  ".css",
  ".sql",
  ".sh",
  ".log",
  ".ini",
  ".toml",
  ".xlsx",
  ".docx",
]);

function canTryTextPreview(file: LibraryFileItem): boolean {
  const ext = (file.ext || "").toLowerCase();
  if (ext === ".pdf" || file.category === "image") return false;
  return TEXT_PREVIEW_EXTS.has(ext) || file.category === "code" || file.category === "spreadsheet";
}

const isPreviewMarkdown = computed(() => {
  const ext = (previewFile.value?.ext || "").toLowerCase();
  return ext === ".md" || ext === ".markdown";
});

const isPreviewHtml = computed(() => {
  const ext = (previewFile.value?.ext || "").toLowerCase();
  return ext === ".html" || ext === ".htm";
});

async function loadFiles() {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams();
    if (searchQuery.value.trim()) params.set("q", searchQuery.value.trim());
    if (categoryFilter.value !== "all") params.set("category", categoryFilter.value);
    if (sourceFilter.value !== "all") params.set("source", sourceFilter.value);
    params.set("page", String(page.value));
    params.set("page_size", String(PAGE_SIZE));

    const res = await api.get<
      | LibraryFileItem[]
      | { items: LibraryFileItem[]; total?: number; page?: number; page_size?: number }
    >(`/library/files?${params.toString()}`);

    if (Array.isArray(res)) {
      files.value = res;
      totalCount.value = null;
      hasNextPage.value = res.length >= PAGE_SIZE;
    } else if (res && Array.isArray(res.items)) {
      files.value = res.items;
      totalCount.value = typeof res.total === "number" ? res.total : res.items.length;
      hasNextPage.value =
        typeof res.total === "number"
          ? page.value * PAGE_SIZE < res.total
          : res.items.length >= PAGE_SIZE;
    } else {
      files.value = [];
      totalCount.value = 0;
      hasNextPage.value = false;
    }
    brokenThumbs.value = {};
  } catch (e: any) {
    error.value = extractError(e, "加载个人资料库失败");
  } finally {
    loading.value = false;
  }
}

watch(searchInput, (val) => {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    if (searchQuery.value !== val) {
      searchQuery.value = val;
      page.value = 1;
      void loadFiles();
    }
  }, 260);
});

function submitSearchNow() {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchQuery.value = searchInput.value;
  page.value = 1;
  void loadFiles();
}

function setCategory(next: CategoryFilter) {
  if (categoryFilter.value === next) return;
  categoryFilter.value = next;
  page.value = 1;
  void loadFiles();
}

function setSource(next: SourceFilter) {
  if (sourceFilter.value === next) return;
  sourceFilter.value = next;
  page.value = 1;
  void loadFiles();
}

function goToPage(nextPage: number) {
  if (nextPage < 1 || nextPage === page.value) return;
  page.value = nextPage;
  void loadFiles();
}

function openUploadPicker() {
  if (uploading.value) return;
  uploadInputRef.value?.click();
}

async function onUploadInputChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const selected = input.files;
  if (!selected || !selected.length) return;
  uploading.value = true;
  error.value = null;
  feedback.value = null;
  try {
    const { uploaded, errors } = await filesStore.uploadToLibrary(selected);
    if (errors.length) {
      error.value = errors.slice(0, 3).join("；");
    }
    if (uploaded.length) {
      feedback.value = `已上传 ${uploaded.length} 个文件到资料库，主聊天与旁聊均可直接参考`;
      page.value = 1;
      await loadFiles();
    }
  } finally {
    uploading.value = false;
    input.value = "";
  }
}

async function resolveDownloadUrl(file: LibraryFileItem, inline: boolean): Promise<string | null> {
  const res = await api.get<{ url: string; expires_in: number }>(
    `/library/files/${encodeURIComponent(file.id)}/download-url?inline=${inline ? "true" : "false"}`,
  );
  if (res?.url) {
    if (inline) {
      const wasExpiring = !file.preview_url || isUrlNearExpiry(file.preview_expires_at);
      file.preview_url = res.url;
      file.preview_expires_at = new Date(Date.now() + (res.expires_in || 300) * 1000).toISOString();
      if (file.category === "image" && (!file.thumb_url || wasExpiring || brokenThumbs.value[file.id])) {
        file.thumb_url = res.url;
        delete brokenThumbs.value[file.id];
      }
    }
    return res.url;
  }
  return null;
}

async function downloadFile(file: LibraryFileItem) {
  downloadingId.value = file.id;
  error.value = null;
  try {
    const url = await resolveDownloadUrl(file, false);
    if (!url) {
      error.value = "暂无法获取文件下载链接，请刷新后重试";
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  } catch (e: any) {
    error.value = extractError(e, "获取下载链接失败");
  } finally {
    downloadingId.value = null;
  }
}

async function openPreview(file: LibraryFileItem) {
  previewFile.value = file;
  previewLoading.value = true;
  previewError.value = null;
  previewUrl.value = null;
  previewText.value = null;
  previewMode.value = "rendered";

  try {
    const ext = (file.ext || "").toLowerCase();
    if (file.category === "image" || ext === ".pdf") {
      let url = file.preview_url ?? null;
      if (!url || isUrlNearExpiry(file.preview_expires_at) || brokenThumbs.value[file.id]) {
        url = await resolveDownloadUrl(file, true);
      }
      if (!url) {
        previewError.value = "临时预览链接已失效或不可用，请刷新列表后重试。";
      } else {
        previewUrl.value = url;
      }
      return;
    }

    if (canTryTextPreview(file)) {
      const res = await api.get<string | { content?: string; text?: string }>(
        `/library/files/${encodeURIComponent(file.id)}/preview-content`,
      );
      const text = typeof res === "string" ? res : (res?.content ?? res?.text ?? null);
      if (typeof text === "string") {
        previewText.value = text;
        return;
      }
      previewUrl.value = file.preview_url ?? null;
      previewError.value = "此文件暂不支持直接在线预览，请点击下方按钮下载后查看。";
      return;
    }

    try {
      previewUrl.value = await resolveDownloadUrl(file, true);
    } catch {
      previewUrl.value = file.preview_url ?? null;
    }
    previewError.value = "该文件格式不支持内置预览，请点击下方按钮下载或在新标签页打开。";
  } catch (e: any) {
    previewError.value = extractError(e, "加载文件预览失败");
  } finally {
    previewLoading.value = false;
  }
}

function closePreview() {
  previewFile.value = null;
  previewUrl.value = null;
  previewText.value = null;
  previewError.value = null;
}

function requestDeleteFile(file: LibraryFileItem) {
  deleteError.value = null;
  deleteTarget.value = file;
}

async function confirmDeleteFile() {
  const target = deleteTarget.value;
  if (!target) return;
  deleting.value = true;
  deleteError.value = null;
  feedback.value = null;
  try {
    await api.delete(`/library/files/${encodeURIComponent(target.id)}`);
    files.value = files.value.filter((f) => f.id !== target.id);
    if (totalCount.value !== null && totalCount.value > 0) {
      totalCount.value -= 1;
    }
    deleteTarget.value = null;
    feedback.value = `已永久删除文件「${target.filename}」，所有聊天将不再参考该文件`;
  } catch (e: any) {
    deleteError.value = extractError(e, "删除文件失败");
  } finally {
    deleting.value = false;
  }
}

onMounted(() => {
  void loadFiles();
});

onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer);
});
</script>

<template>
  <div class="space-y-5">
    <input
      ref="uploadInputRef"
      type="file"
      multiple
      :accept="ACCEPT_ATTR"
      class="sr-only"
      @change="onUploadInputChange"
    />

    <!-- Filter & Search Bar Card -->
    <section class="space-y-4 rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h2 class="text-[15.5px] font-semibold text-fg">
              {{ props.embedded ? "全部资料" : "文件与资料资产" }}
            </h2>
            <BaseBadge tone="gray">
              {{ totalCount !== null ? `共 ${totalCount} 项` : `本页 ${files.length} 项` }}
            </BaseBadge>
          </div>
          <p class="mt-1 text-[13px] text-fg-muted">
            统一管理主聊天与旁聊中的所有上传文件及 AI 产出；所有文件默认全局可参考，删除后所有聊天将无法再访问。
          </p>
        </div>

        <div class="flex shrink-0 items-center gap-2">
          <BaseButton size="sm" rounded="full" :loading="uploading" @click="openUploadPicker">
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
              <path stroke-linecap="round" d="M12 5v14M5 12h14" />
            </svg>
            <span>上传文件</span>
          </BaseButton>
          <BaseButton variant="soft" size="sm" rounded="full" :disabled="loading" @click="loadFiles">
            刷新
          </BaseButton>
        </div>
      </div>

      <!-- Search Bar -->
      <form class="relative" @submit.prevent="submitSearchNow">
        <svg
          class="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-faint"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <circle cx="11" cy="11" r="7" />
          <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
        </svg>
        <input
          v-model="searchInput"
          type="search"
          placeholder="搜索文件名…"
          aria-label="搜索个人资料库文件"
          class="focus-ring h-10 w-full rounded-xl border border-line/80 bg-canvas pl-10 pr-4 text-[13.5px] text-fg placeholder:text-fg-faint hover:border-line-strong"
        />
      </form>

      <!-- Filter Pills -->
      <div class="flex flex-wrap items-center gap-x-4 gap-y-2.5 text-[12px]">
        <!-- Category -->
        <div class="flex flex-wrap items-center gap-1.5" role="group" aria-label="按类型筛选">
          <span class="mr-0.5 text-fg-faint">类型</span>
          <button
            v-for="opt in [
              { value: 'all', label: '全部' },
              { value: 'document', label: '文档' },
              { value: 'spreadsheet', label: '表格' },
              { value: 'code', label: '代码' },
              { value: 'image', label: '图片' },
            ] as const"
            :key="opt.value"
            type="button"
            class="focus-ring rounded-full px-2.5 py-1 font-medium transition-colors"
            :class="
              categoryFilter === opt.value
                ? 'bg-primary text-primary-fg'
                : 'bg-canvas text-fg-muted hover:bg-hover hover:text-fg'
            "
            @click="setCategory(opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>

        <!-- Source -->
        <div class="flex flex-wrap items-center gap-1.5" role="group" aria-label="按来源筛选">
          <span class="mr-0.5 text-fg-faint">来源</span>
          <button
            v-for="opt in [
              { value: 'all', label: '全部来源' },
              { value: 'user', label: '我上传的' },
              { value: 'assistant', label: 'AI 产出' },
            ] as const"
            :key="opt.value"
            type="button"
            class="focus-ring rounded-full px-2.5 py-1 font-medium transition-colors"
            :class="
              sourceFilter === opt.value
                ? 'bg-primary text-primary-fg'
                : 'bg-canvas text-fg-muted hover:bg-hover hover:text-fg'
            "
            @click="setSource(opt.value)"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>
    </section>

    <FormError :message="error" />
    <div
      v-if="feedback"
      role="status"
      aria-live="polite"
      class="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-success-weak px-4 py-2.5 text-[13px] text-success"
    >
      <span>{{ feedback }}</span>
    </div>

    <!-- Loading -->
    <div
      v-if="loading && !files.length"
      class="flex items-center justify-center gap-2 rounded-[24px] bg-sidebar py-12 text-[13.5px] text-fg-muted dark:bg-surface"
    >
      <Spinner :size="18" />
      <span>正在加载资料库文件…</span>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!files.length"
      class="rounded-[24px] bg-sidebar px-6 py-12 text-center text-[13.5px] text-fg-muted dark:bg-surface"
    >
      暂无符合条件的文件。你在对话中上传的文件或 AI 生成的工作区文件都会归档在此处。
    </div>

    <!-- Responsive File Grid -->
    <div v-else class="grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="file in files"
        :key="file.id"
        class="flex flex-col justify-between gap-3.5 rounded-[24px] bg-sidebar p-4.5 transition-colors dark:bg-surface"
      >
        <!-- File Header: Thumbnail / Type Tile + Metadata -->
        <div class="flex items-start gap-3">
          <button
            type="button"
            class="focus-ring group relative h-14 w-14 shrink-0 overflow-hidden rounded-xl bg-canvas ring-1 ring-line/80"
            :aria-label="`预览 ${file.filename}`"
            @click="openPreview(file)"
          >
            <img
              v-if="file.category === 'image' && (file.thumb_url || file.preview_url) && !brokenThumbs[file.id]"
              :src="file.thumb_url || file.preview_url || ''"
              :alt="file.filename"
              loading="lazy"
              class="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
              @error="brokenThumbs[file.id] = true"
            />
            <span
              v-else
              class="flex h-full w-full items-center justify-center px-1 text-center text-[11px] font-semibold text-fg-muted"
            >
              {{ categoryLabel(file.category, file.ext) }}
            </span>
          </button>

          <div class="min-w-0 flex-1">
            <button
              type="button"
              class="focus-ring block max-w-full truncate text-left text-[14px] font-semibold text-fg hover:underline"
              :title="file.filename"
              @click="openPreview(file)"
            >
              {{ file.filename }}
            </button>

            <div class="mt-1 flex flex-wrap items-center gap-1.5">
              <BaseBadge :tone="file.source === 'assistant' ? 'brand' : 'gray'">
                {{ file.source === "assistant" ? "AI 生成" : "用户上传" }}
              </BaseBadge>
              <span class="text-[11.5px] tabular-nums text-fg-faint">{{ formatFileSize(file.size_bytes) }}</span>
              <span class="text-[11.5px] text-fg-faint">· {{ formatDate(file.created_at) }}</span>
            </div>

            <p class="mt-1 truncate text-[12px] text-fg-muted" :title="file.conversation_title || undefined">
              来源：{{ file.conversation_title || (file.conversation_id ? "原聊天" : "资料库直传") }}
            </p>
          </div>
        </div>

        <!-- Actions Footer -->
        <div class="flex flex-wrap items-center justify-end gap-1 border-t border-line/60 pt-2.5">
          <BaseButton variant="ghost" size="sm" rounded="full" @click="openPreview(file)">
            预览
          </BaseButton>
          <BaseButton
            variant="ghost"
            size="sm"
            rounded="full"
            :loading="downloadingId === file.id"
            @click="downloadFile(file)"
          >
            下载
          </BaseButton>
          <BaseButton
            variant="ghost"
            size="sm"
            rounded="full"
            class="text-danger hover:bg-danger-weak hover:text-danger"
            @click="requestDeleteFile(file)"
          >
            删除
          </BaseButton>
        </div>
      </article>
    </div>

    <!-- Pagination -->
    <div v-if="page > 1 || hasNextPage" class="flex items-center justify-between gap-3 pt-1">
      <BaseButton variant="soft" size="sm" rounded="full" :disabled="page <= 1 || loading" @click="goToPage(page - 1)">
        上一页
      </BaseButton>
      <span class="text-[12.5px] tabular-nums text-fg-muted">
        第 {{ page }} 页
        <template v-if="totalCount !== null"> · 共 {{ Math.max(1, Math.ceil(totalCount / PAGE_SIZE)) }} 页</template>
      </span>
      <BaseButton variant="soft" size="sm" rounded="full" :disabled="!hasNextPage || loading" @click="goToPage(page + 1)">
        下一页
      </BaseButton>
    </div>

    <!-- Preview Modal -->
    <BaseModal
      :open="!!previewFile"
      :title="previewFile?.filename ?? '文件预览'"
      width="50rem"
      @close="closePreview"
    >
      <div v-if="previewFile" class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-1.5 text-[12px] text-fg-muted">
            <BaseBadge tone="gray">{{ categoryLabel(previewFile.category, previewFile.ext) }}</BaseBadge>
            <span class="tabular-nums">{{ formatFileSize(previewFile.size_bytes) }}</span>
            <span>· {{ previewFile.source === "assistant" ? "AI 生成" : "用户上传" }}</span>
          </div>

          <div v-if="(isPreviewMarkdown || isPreviewHtml) && previewText !== null" class="flex items-center gap-1 rounded-full bg-surface p-0.5">
            <button
              type="button"
              class="focus-ring rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors"
              :class="previewMode === 'rendered' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
              @click="previewMode = 'rendered'"
            >
              渲染预览
            </button>
            <button
              type="button"
              class="focus-ring rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors"
              :class="previewMode === 'source' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
              @click="previewMode = 'source'"
            >
              源码
            </button>
          </div>
        </div>

        <div v-if="previewLoading" class="flex items-center justify-center gap-2 py-12 text-[13.5px] text-fg-muted">
          <Spinner :size="18" />
          <span>正在加载预览…</span>
        </div>

        <div v-else-if="previewError" class="space-y-3 rounded-2xl bg-surface/70 p-6 text-center">
          <p class="text-[13.5px] text-fg-muted">{{ previewError }}</p>
          <div class="flex justify-center gap-2">
            <BaseButton size="sm" rounded="full" @click="downloadFile(previewFile)">
              下载文件
            </BaseButton>
          </div>
        </div>

        <!-- Image Preview -->
        <div v-else-if="previewFile.category === 'image' && previewUrl" class="flex max-h-[65dvh] items-center justify-center overflow-auto rounded-2xl bg-surface/50 p-2">
          <img
            :src="previewUrl"
            :alt="previewFile.filename"
            class="max-h-[60dvh] max-w-full rounded-xl object-contain"
          />
        </div>

        <!-- PDF Preview -->
        <iframe
          v-else-if="(previewFile.ext || '').toLowerCase() === '.pdf' && previewUrl"
          :src="previewUrl"
          :title="previewFile.filename"
          class="h-[65dvh] w-full rounded-2xl border border-line bg-canvas"
        />

        <!-- Markdown Preview -->
        <div
          v-else-if="isPreviewMarkdown && previewText !== null && previewMode === 'rendered'"
          v-scrollbar
          class="custom-scrollbar max-h-[65dvh] overflow-auto rounded-2xl border border-line/70 bg-canvas p-4"
        >
          <MarkdownRenderer :content="previewText" />
        </div>

        <!-- HTML Sandbox Preview -->
        <iframe
          v-else-if="isPreviewHtml && previewText !== null && previewMode === 'rendered'"
          sandbox="allow-scripts"
          :srcdoc="previewText"
          :title="previewFile.filename"
          class="h-[65dvh] w-full rounded-2xl border border-line bg-white"
        />

        <!-- Text / Code / Source Fallback -->
        <pre
          v-else-if="previewText !== null"
          v-scrollbar
          class="custom-scrollbar max-h-[65dvh] overflow-auto rounded-2xl bg-surface p-4 font-mono text-[12.5px] leading-relaxed text-fg whitespace-pre-wrap break-words dark:bg-canvas"
        >{{ previewText }}</pre>
      </div>

      <template #footer>
        <BaseButton
          v-if="previewFile"
          variant="secondary"
          rounded="full"
          :loading="downloadingId === previewFile.id"
          @click="downloadFile(previewFile)"
        >
          下载文件
        </BaseButton>
        <BaseButton variant="soft" rounded="full" @click="closePreview">关闭</BaseButton>
      </template>
    </BaseModal>

    <!-- Delete File Confirmation Modal -->
    <BaseModal
      :open="!!deleteTarget"
      title="删除文件"
      @close="deleteTarget = null"
    >
      <div v-if="deleteTarget" class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          确定要从资料库永久删除
          <strong class="font-medium text-fg">{{ deleteTarget.filename }}</strong>
          吗？删除后，主聊天和所有旁聊都将无法再参考该文件。
        </p>
        <FormError :message="deleteError" />
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="deleting" @click="deleteTarget = null">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="deleting" @click="confirmDeleteFile">
          确认删除
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
