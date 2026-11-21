<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import hljs from "highlight.js/lib/common";
import { getFileExt } from "../../lib/fileTypes";
import { isWritableTextExt } from "../../lib/fileTokens";
import { useFilesStore } from "../../stores/files";
import type { DeliverableTarget } from "../../types";
import BaseModal from "../ui/BaseModal.vue";
import Spinner from "../ui/Spinner.vue";
import CsvTableEditor from "./CsvTableEditor.vue";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const HLJS_LANG_MAP: Record<string, string> = {
  ".html": "xml",
  ".htm": "xml",
  ".xml": "xml",
  ".svg": "xml",
  ".vue": "xml",
  ".md": "markdown",
  ".markdown": "markdown",
  ".py": "python",
  ".js": "javascript",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".jsx": "javascript",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".css": "css",
  ".scss": "scss",
  ".sql": "sql",
  ".sh": "bash",
  ".bash": "bash",
  ".zsh": "bash",
  ".json": "json",
  ".jsonl": "json",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".ini": "ini",
  ".toml": "ini",
};

const props = defineProps<{
  target: DeliverableTarget | null;
}>();

const emit = defineEmits<{
  close: [];
}>();

const filesStore = useFilesStore();

const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const saveNotice = ref<string | null>(null);
const content = ref("");
const editDraft = ref("");
const editingSource = ref(false);
const truncated = ref(false);
const viewMode = ref<"preview" | "source">("preview");
const fullscreen = ref(false);
const copied = ref(false);
const isDarkTheme = ref(
  typeof document !== "undefined" ? document.documentElement.classList.contains("dark") : false,
);

let themeObserver: MutationObserver | null = null;
let loadSeq = 0;

const open = computed(() => props.target !== null);

const ext = computed(() => {
  if (!props.target) return ".txt";
  return getFileExt(props.target.filename).toLowerCase() || ".txt";
});

const kind = computed<"html" | "markdown" | "table" | "code">(() => {
  if (ext.value === ".html" || ext.value === ".htm") return "html";
  if (ext.value === ".md" || ext.value === ".markdown") return "markdown";
  if (ext.value === ".csv" || ext.value === ".tsv") return "table";
  return "code";
});

const canEdit = computed(() => !truncated.value && isWritableTextExt(ext.value));
const supportsPreviewMode = computed(() => kind.value === "html" || kind.value === "markdown" || kind.value === "table");

const modalWidth = computed(() => (fullscreen.value ? "calc(100dvw - 2rem)" : "min(92vw, 1140px)"));

const badgeLabel = computed(() => {
  if (kind.value === "html") return "HTML";
  if (kind.value === "markdown") return "Markdown";
  if (kind.value === "table") return ext.value === ".tsv" ? "TSV" : "CSV";
  return ext.value.replace(".", "").toUpperCase() || "TEXT";
});

function injectHtmlTheme(rawHtml: string, dark: boolean): string {
  const theme = dark ? "dark" : "light";
  const themeTag =
    `<meta name="color-scheme" content="${theme}">` +
    `<style data-whitz-theme>:root{color-scheme:${theme};--whitz-theme:${theme};}</style>` +
    `<script>(function(){try{document.documentElement.setAttribute("data-theme","${theme}");document.documentElement.classList.toggle("dark",${dark});}catch(e){}})();<\/script>`;

  if (/<head[\s>]/i.test(rawHtml)) {
    return rawHtml.replace(/<head([^>]*)>/i, `<head$1>${themeTag}`);
  }
  if (/<html[\s>]/i.test(rawHtml)) {
    return rawHtml.replace(/<html([^>]*)>/i, `<html$1><head>${themeTag}</head>`);
  }
  return `<!doctype html><html data-theme="${theme}" class="${dark ? "dark" : ""}"><head><meta charset="utf-8">${themeTag}</head><body>${rawHtml}</body></html>`;
}

const themedHtml = computed(() => {
  if (kind.value !== "html" || !content.value) return "";
  return injectHtmlTheme(content.value, isDarkTheme.value);
});

const highlightedHtml = ref("");
let domPurifyPromise: Promise<typeof import("dompurify").default> | undefined;
function loadDOMPurify() {
  domPurifyPromise ??= import("dompurify").then((m) => m.default ?? m);
  return domPurifyPromise;
}

let hlSeq = 0;
watch(
  [content, ext],
  async ([code, curExt]) => {
    const seq = ++hlSeq;
    highlightedHtml.value = "";
    if (!code) return;
    const lang = HLJS_LANG_MAP[curExt];
    if (!lang || !hljs.getLanguage(lang)) return;
    try {
      const raw = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
      const DOMPurify = await loadDOMPurify();
      if (seq !== hlSeq) return;
      highlightedHtml.value = DOMPurify.sanitize(raw, {
        ALLOWED_TAGS: ["span"],
        ALLOWED_ATTR: ["class"],
      });
    } catch {
      if (seq === hlSeq) highlightedHtml.value = "";
    }
  },
  { immediate: true },
);

async function loadContent() {
  if (!props.target) return;
  const seq = ++loadSeq;
  loading.value = true;
  error.value = null;
  saveNotice.value = null;
  editingSource.value = false;
  content.value = "";
  truncated.value = false;
  viewMode.value = supportsPreviewMode.value ? "preview" : "source";

  try {
    const res = await filesStore.fetchPreviewContent(
      props.target.fileId,
      props.target.conversationId ?? undefined,
    );
    if (seq !== loadSeq) return;
    content.value = res.content ?? "";
    truncated.value = Boolean(res.truncated);
  } catch (e: any) {
    if (seq !== loadSeq) return;
    error.value = e?.detail?.detail ?? e?.message ?? "无法加载交付文件内容";
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

watch(
  () => props.target,
  (next) => {
    if (next) {
      fullscreen.value = false;
      void loadContent();
    }
  },
  { immediate: true },
);

function startSourceEdit() {
  if (!canEdit.value) return;
  editDraft.value = content.value;
  viewMode.value = "source";
  editingSource.value = true;
  saveNotice.value = null;
}

function cancelSourceEdit() {
  editingSource.value = false;
  editDraft.value = "";
}

async function saveContentText(nextText: string) {
  if (!props.target || saving.value) return;
  saving.value = true;
  error.value = null;
  saveNotice.value = null;
  try {
    await filesStore.updateFileContent(
      props.target.fileId,
      nextText,
      props.target.conversationId ?? undefined,
    );
    content.value = nextText;
    editingSource.value = false;
    saveNotice.value = "已保存到工作区";
    window.setTimeout(() => {
      saveNotice.value = null;
    }, 2200);
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "保存失败，请重试";
  } finally {
    saving.value = false;
  }
}

function openHtmlInNewTab() {
  if (kind.value !== "html" || !content.value) return;
  const blob = new Blob([themedHtml.value || content.value], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function downloadFile() {
  if (!props.target) return;
  const mime =
    kind.value === "html"
      ? "text/html;charset=utf-8"
      : kind.value === "table"
        ? "text/csv;charset=utf-8"
        : "text/plain;charset=utf-8";
  const blob = new Blob([content.value], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = props.target.filename || "deliverable.txt";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function copyAll() {
  if (!content.value) return;
  try {
    await navigator.clipboard.writeText(content.value);
    copied.value = true;
    window.setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    /* ignore */
  }
}

onMounted(() => {
  if (typeof document !== "undefined") {
    isDarkTheme.value = document.documentElement.classList.contains("dark");
    themeObserver = new MutationObserver(() => {
      isDarkTheme.value = document.documentElement.classList.contains("dark");
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }
});

onBeforeUnmount(() => {
  themeObserver?.disconnect();
  themeObserver = null;
});
</script>

<template>
  <BaseModal :open="open" :width="modalWidth" flush @close="emit('close')">
    <div
      class="flex flex-col overflow-hidden"
      :class="fullscreen ? 'h-[calc(100dvh-2rem)]' : 'h-[min(82dvh,760px)]'"
    >
      <!-- Header Toolbar -->
      <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3.5">
        <div class="flex min-w-0 items-center gap-2.5">
          <span class="shrink-0 rounded-lg bg-accent-weak/85 px-2 py-0.5 text-[11px] font-semibold text-accent">
            {{ badgeLabel }}
          </span>
          <div class="min-w-0">
            <h3 class="truncate text-[15px] font-semibold text-fg" :title="target?.title || target?.filename">
              {{ target?.title || target?.filename }}
            </h3>
            <p v-if="target?.title && target?.filename && target.title !== target.filename" class="truncate text-[11.5px] text-fg-faint">
              {{ target.filename }}
            </p>
          </div>
          <span v-if="saveNotice" class="rounded-full bg-success/15 px-2 py-0.5 text-[11px] font-medium text-success">
            {{ saveNotice }}
          </span>
        </div>

        <div class="flex shrink-0 flex-wrap items-center gap-1.5">
          <!-- Mode toggle -->
          <div v-if="supportsPreviewMode" class="inline-flex rounded-lg bg-surface p-0.5 text-[12px]">
            <button
              type="button"
              class="focus-ring rounded-md px-2.5 py-1 font-medium transition-colors"
              :class="viewMode === 'preview' ? 'bg-canvas text-fg shadow-2xs' : 'text-fg-muted hover:text-fg'"
              @click="editingSource = false; viewMode = 'preview'"
            >
              {{ kind === "table" ? "表格视图" : "渲染预览" }}
            </button>
            <button
              type="button"
              class="focus-ring rounded-md px-2.5 py-1 font-medium transition-colors"
              :class="viewMode === 'source' ? 'bg-canvas text-fg shadow-2xs' : 'text-fg-muted hover:text-fg'"
              @click="viewMode = 'source'"
            >
              源码
            </button>
          </div>

          <!-- Open HTML in new tab -->
          <button
            v-if="kind === 'html' && content"
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-lg bg-surface px-2.5 py-1.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            title="在新标签页中独立打开此 HTML 页面"
            @click="openHtmlInNewTab"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M14 3h7v7M10 14L21 3M21 14v5a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h5" />
            </svg>
            <span class="hidden sm:inline">新标签页打开</span>
          </button>

          <!-- Edit source -->
          <template v-if="canEdit && (viewMode === 'source' || kind === 'code')">
            <template v-if="editingSource">
              <button
                type="button"
                class="focus-ring rounded-lg px-2.5 py-1.5 text-[12px] font-medium text-fg-muted hover:bg-hover hover:text-fg"
                :disabled="saving"
                @click="cancelSourceEdit"
              >
                取消
              </button>
              <button
                type="button"
                class="focus-ring inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-[12px] font-medium text-primary-fg hover:bg-primary-hover disabled:opacity-50"
                :disabled="saving"
                @click="saveContentText(editDraft)"
              >
                <Spinner v-if="saving" :size="12" />
                <span>保存</span>
              </button>
            </template>
            <button
              v-else
              type="button"
              class="focus-ring rounded-lg bg-surface px-2.5 py-1.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              @click="startSourceEdit"
            >
              编辑
            </button>
          </template>

          <button
            v-if="content"
            type="button"
            class="focus-ring rounded-lg bg-surface px-2.5 py-1.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="copyAll"
          >
            {{ copied ? "已复制" : "复制" }}
          </button>

          <button
            type="button"
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            title="刷新内容"
            aria-label="刷新内容"
            @click="loadContent"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 12a9 9 0 0115.3-6.4L21 8M21 3v5h-5M21 12a9 9 0 01-15.3 6.4L3 16M3 21v-5h5" />
            </svg>
          </button>

          <button
            type="button"
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            title="下载文件"
            aria-label="下载文件"
            @click="downloadFile"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
          </button>

          <button
            type="button"
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :title="fullscreen ? '退出全屏' : '全屏查看'"
            :aria-label="fullscreen ? '退出全屏' : '全屏查看'"
            @click="fullscreen = !fullscreen"
          >
            <svg v-if="fullscreen" class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8 3v3a2 2 0 01-2 2H3m18 0h-3a2 2 0 01-2-2V3m0 18v-3a2 2 0 012-2h3M3 16h3a2 2 0 012 2v3" />
            </svg>
            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3" />
            </svg>
          </button>

          <button
            type="button"
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
            aria-label="关闭"
            @click="emit('close')"
          >
            <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Body -->
      <div class="relative flex min-h-0 flex-1 flex-col bg-canvas">
        <div v-if="loading" class="flex flex-1 items-center justify-center gap-2 text-[13.5px] text-fg-muted">
          <Spinner :size="16" />
          <span>正在加载交付内容…</span>
        </div>

        <div v-else-if="error" class="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <p class="text-[13.5px] text-danger">{{ error }}</p>
          <button
            type="button"
            class="focus-ring rounded-full bg-surface px-4 py-1.5 text-[12.5px] font-medium text-fg hover:bg-hover"
            @click="loadContent"
          >
            重试加载
          </button>
        </div>

        <template v-else>
          <!-- HTML Preview -->
          <iframe
            v-if="kind === 'html' && viewMode === 'preview'"
            :key="`html-${isDarkTheme ? 'dark' : 'light'}`"
            :srcdoc="themedHtml"
            sandbox="allow-scripts allow-forms allow-popups"
            referrerpolicy="no-referrer"
            class="h-full w-full flex-1 border-0 bg-white dark:bg-[#111]"
            :title="target?.title || target?.filename || 'HTML 预览'"
          />

          <!-- CSV / TSV Interactive Table -->
          <CsvTableEditor
            v-else-if="kind === 'table' && viewMode === 'preview'"
            :content="content"
            :delimiter="ext === '.tsv' ? '\t' : ','"
            :readonly="!canEdit"
            :saving="saving"
            @save="saveContentText"
          />

          <!-- Markdown Rendered Preview -->
          <div
            v-else-if="kind === 'markdown' && viewMode === 'preview'"
            v-scrollbar
            class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-6 py-5"
          >
            <MarkdownRenderer :content="content" />
          </div>

          <!-- Source Editor -->
          <div v-else-if="editingSource" class="flex min-h-0 flex-1 flex-col p-4">
            <textarea
              v-model="editDraft"
              v-scrollbar
              spellcheck="false"
              class="custom-scrollbar min-h-0 flex-1 resize-none rounded-xl border border-line bg-sidebar p-4 font-mono text-[13px] leading-relaxed text-fg outline-none focus:border-accent"
            />
          </div>

          <!-- Highlighted Source View -->
          <div v-else v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-auto p-5">
            <pre
              class="m-0 font-mono text-[13px] leading-relaxed text-fg whitespace-pre-wrap break-words"
            ><code v-if="highlightedHtml" class="hljs" v-html="highlightedHtml" /><code v-else>{{ content }}</code></pre>
            <p v-if="truncated" class="mt-3 text-[12px] text-fg-faint">
              文件较大，当前仅展示前部分预览，完整内容请下载查看。
            </p>
          </div>
        </template>
      </div>
    </div>
  </BaseModal>
</template>
