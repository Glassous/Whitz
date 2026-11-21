<script setup lang="ts">
import { computed, ref, watch } from "vue";
import hljs from "highlight.js/lib/common";
import { categoryLabel, formatFileSize, getFileExt } from "../../lib/fileTypes";
import { isWritableTextExt } from "../../lib/fileTokens";
import { useFilesStore } from "../../stores/files";
import type { ConversationFile, DeliverableTarget, PreviewTarget } from "../../types";
import Spinner from "../ui/Spinner.vue";
import CsvTableEditor from "./CsvTableEditor.vue";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

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
  target: PreviewTarget;
  hideHeader?: boolean;
  resizing?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  download: [file: ConversationFile];
  "open-deliverable": [target: DeliverableTarget];
}>();

const filesStore = useFilesStore();

const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const saveNotice = ref<string | null>(null);
const textContent = ref("");
const editDraft = ref("");
const editingSource = ref(false);
const truncated = ref(false);
const freshUrl = ref<string | null>(null);
const viewMode = ref<"preview" | "source">("preview");
const imageActualSize = ref(false);
const copied = ref(false);

let loadSeq = 0;

const targetExt = computed(() => {
  if (props.target.kind === "html") return ".html";
  const ext = props.target.file.ext || getFileExt(props.target.file.filename);
  return ext.toLowerCase();
});

const previewKind = computed<"html" | "markdown" | "image" | "pdf" | "table" | "code">(() => {
  if (props.target.kind === "html") return "html";
  const ext = targetExt.value;
  if (ext === ".html" || ext === ".htm") return "html";
  if (ext === ".md" || ext === ".markdown") return "markdown";
  if (props.target.file.category === "image" || IMAGE_EXTS.has(ext)) return "image";
  if (ext === ".pdf") return "pdf";
  if (ext === ".csv" || ext === ".tsv") return "table";
  return "code";
});

const titleText = computed(() =>
  props.target.kind === "html" ? props.target.title || "HTML 预览" : props.target.file.filename,
);

const typeBadge = computed(() => {
  if (props.target.kind === "html") return "HTML";
  return categoryLabel(props.target.file.category, props.target.file.ext);
});

const supportsModeToggle = computed(
  () => previewKind.value === "html" || previewKind.value === "markdown" || previewKind.value === "table",
);

const canCopyText = computed(
  () => (previewKind.value === "html" || previewKind.value === "markdown" || previewKind.value === "table" || previewKind.value === "code") && textContent.value.length > 0,
);

const canEditFile = computed(
  () => props.target.kind === "file" && !truncated.value && isWritableTextExt(targetExt.value),
);

function startSourceEdit() {
  if (!canEditFile.value) return;
  editDraft.value = textContent.value;
  viewMode.value = "source";
  editingSource.value = true;
  saveNotice.value = null;
}

function cancelSourceEdit() {
  editingSource.value = false;
  editDraft.value = "";
}

async function saveEditedText(nextText: string) {
  if (props.target.kind !== "file" || saving.value) return;
  saving.value = true;
  error.value = null;
  saveNotice.value = null;
  try {
    await filesStore.updateFileContent(
      props.target.file.id,
      nextText,
      props.target.file.conversation_id ?? undefined,
    );
    textContent.value = nextText;
    editingSource.value = false;
    saveNotice.value = "已保存";
    window.setTimeout(() => {
      saveNotice.value = null;
    }, 2000);
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "保存失败，请重试";
  } finally {
    saving.value = false;
  }
}

function openInModal() {
  if (props.target.kind !== "file") return;
  emit("open-deliverable", {
    fileId: props.target.file.id,
    filename: props.target.file.filename,
    title: props.target.file.filename,
    conversationId: props.target.file.conversation_id ?? undefined,
  });
}

const highlightedCodeHtml = ref("");

let domPurifyPromise: Promise<typeof import("dompurify").default> | undefined;
function loadDOMPurify() {
  domPurifyPromise ??= import("dompurify").then((mod) => mod.default ?? mod);
  return domPurifyPromise;
}

let highlightSeq = 0;
watch(
  [textContent, targetExt],
  async ([code, ext]) => {
    const seq = ++highlightSeq;
    highlightedCodeHtml.value = "";
    if (!code) return;
    const lang = HLJS_LANG_MAP[ext];
    if (!lang || !hljs.getLanguage(lang)) return;
    try {
      const raw = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
      const DOMPurify = await loadDOMPurify();
      if (seq !== highlightSeq) return;
      highlightedCodeHtml.value = DOMPurify.sanitize(raw, {
        ALLOWED_TAGS: ["span"],
        ALLOWED_ATTR: ["class"],
      });
    } catch {
      if (seq === highlightSeq) highlightedCodeHtml.value = "";
    }
  },
  { immediate: true },
);

async function loadTarget() {
  const seq = ++loadSeq;
  loading.value = true;
  error.value = null;
  editingSource.value = false;
  saveNotice.value = null;
  textContent.value = "";
  truncated.value = false;
  freshUrl.value = null;
  imageActualSize.value = false;

  if (props.target.kind === "html") {
    viewMode.value = "preview";
    textContent.value = props.target.html;
    loading.value = false;
    return;
  }

  const file = props.target.file;
  viewMode.value =
    previewKind.value === "html" || previewKind.value === "markdown" || previewKind.value === "table"
      ? "preview"
      : "source";

  try {
    if (previewKind.value === "image" || previewKind.value === "pdf") {
      if (props.target.previewUrl) {
        freshUrl.value = props.target.previewUrl;
      } else {
        const url = await filesStore.ensureFreshUrl(file);
        if (seq !== loadSeq) return;
        if (!url) throw new Error("无法获取临时预览链接");
        freshUrl.value = url;
      }
      return;
    }

    if (typeof props.target.content === "string") {
      textContent.value = props.target.content;
      return;
    }

    const res = await filesStore.fetchPreviewContent(file.id, file.conversation_id ?? undefined);
    if (seq !== loadSeq) return;
    let content = res.content;
    if (targetExt.value === ".json" && !res.truncated) {
      try {
        content = JSON.stringify(JSON.parse(content), null, 2);
      } catch {
        /* keep raw text */
      }
    }
    textContent.value = content;
    truncated.value = Boolean(res.truncated);
  } catch (e: any) {
    if (seq !== loadSeq) return;
    error.value = e?.detail?.detail ?? e?.message ?? "该文件暂不支持在线预览，请下载后查看";
  } finally {
    if (seq === loadSeq) loading.value = false;
  }
}

async function refreshMediaUrl() {
  if (props.target.kind !== "file") return;
  loading.value = true;
  error.value = null;
  try {
    const url = await filesStore.ensureFreshUrl(props.target.file, true);
    if (!url) throw new Error("刷新预览链接失败");
    freshUrl.value = url;
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "预览链接刷新失败";
  } finally {
    loading.value = false;
  }
}

function onDownload() {
  if (props.target.kind === "file") {
    emit("download", props.target.file);
    return;
  }
  const blob = new Blob([props.target.html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "preview.html";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function copySource() {
  if (!textContent.value) return;
  try {
    await navigator.clipboard.writeText(textContent.value);
    copied.value = true;
    window.setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    /* ignore */
  }
}

watch(() => props.target, () => {
  void loadTarget();
}, { immediate: true });
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-sidebar">
    <!-- Preview Header Bar -->
    <div
      class="shrink-0 border-b border-line px-3.5 pb-2.5 pt-3"
      :class="hideHeader ? '' : 'lg:pr-14'"
    >
      <div class="flex items-center justify-between gap-2">
        <button
          type="button"
          class="focus-ring inline-flex h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="emit('close')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
          </svg>
          <span>返回步骤与文件</span>
        </button>

        <div class="flex shrink-0 items-center gap-1.5">
          <!-- Mode toggle for HTML / Markdown / CSV -->
          <div
            v-if="supportsModeToggle"
            class="inline-flex rounded-lg bg-surface p-0.5 text-[11.5px]"
          >
            <button
              type="button"
              class="focus-ring rounded-md px-2 py-1 font-medium transition-colors"
              :class="viewMode === 'preview' ? 'bg-canvas text-fg shadow-2xs' : 'text-fg-muted hover:text-fg'"
              @click="viewMode = 'preview'"
            >
              {{ previewKind === "table" ? "表格" : "渲染预览" }}
            </button>
            <button
              type="button"
              class="focus-ring rounded-md px-2 py-1 font-medium transition-colors"
              :class="viewMode === 'source' ? 'bg-canvas text-fg shadow-2xs' : 'text-fg-muted hover:text-fg'"
              @click="viewMode = 'source'"
            >
              源码
            </button>
          </div>

          <!-- Image zoom toggle -->
          <button
            v-if="previewKind === 'image' && freshUrl"
            type="button"
            class="focus-ring rounded-lg bg-surface px-2 py-1 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="imageActualSize = !imageActualSize"
          >
            {{ imageActualSize ? "适应窗口" : "原始尺寸" }}
          </button>

          <!-- Copy source button -->
          <button
            v-if="canCopyText && !editingSource"
            type="button"
            class="focus-ring flex h-7.5 items-center gap-1 rounded-lg bg-surface px-2 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :title="copied ? '已复制' : '复制内容'"
            @click="copySource"
          >
            <span>{{ copied ? "已复制" : "复制" }}</span>
          </button>

          <!-- Edit / Save for writable text files -->
          <template v-if="canEditFile && (viewMode === 'source' || previewKind === 'code')">
            <template v-if="editingSource">
              <button
                type="button"
                class="focus-ring flex h-7.5 items-center rounded-lg px-2 text-[11.5px] font-medium text-fg-muted hover:bg-hover hover:text-fg"
                :disabled="saving"
                @click="cancelSourceEdit"
              >
                取消
              </button>
              <button
                type="button"
                class="focus-ring inline-flex h-7.5 items-center gap-1 rounded-lg bg-primary px-2.5 text-[11.5px] font-medium text-primary-fg hover:bg-primary-hover disabled:opacity-50"
                :disabled="saving"
                @click="saveEditedText(editDraft)"
              >
                <Spinner v-if="saving" :size="11" />
                <span>保存</span>
              </button>
            </template>
            <button
              v-else
              type="button"
              class="focus-ring flex h-7.5 items-center rounded-lg bg-surface px-2 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              @click="startSourceEdit"
            >
              编辑
            </button>
          </template>

          <!-- Pop out to large modal for text deliverables -->
          <button
            v-if="canEditFile && !editingSource"
            type="button"
            class="focus-ring flex h-7.5 items-center rounded-lg bg-surface px-2 text-[11.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            title="在居中大弹窗中查看"
            @click="openInModal"
          >
            弹窗查看
          </button>

          <!-- Download button -->
          <button
            type="button"
            class="focus-ring inline-flex h-7.5 items-center gap-1 rounded-lg bg-canvas px-2.5 text-[12px] font-medium text-fg transition-colors hover:bg-hover"
            title="下载文件"
            @click="onDownload"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
            <span>下载</span>
          </button>
        </div>
      </div>

      <!-- Filename & badge sub-row -->
      <div class="mt-2 flex items-center gap-2">
        <span class="shrink-0 rounded-md bg-surface px-1.5 py-0.5 text-[11px] font-medium text-fg-muted">
          {{ typeBadge }}
        </span>
        <p class="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-fg" :title="titleText">
          {{ titleText }}
        </p>
        <span v-if="target.kind === 'file'" class="shrink-0 text-[11.5px] tabular-nums text-fg-faint">
          {{ formatFileSize(target.file.size_bytes) }}
        </span>
      </div>
    </div>

    <!-- Preview Content Body -->
    <div class="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <div v-if="loading" class="flex flex-1 items-center justify-center p-6 text-[13px] text-fg-faint">
        正在加载预览内容…
      </div>

      <div v-else-if="error" class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <p class="text-[13.5px] text-fg-muted">{{ error }}</p>
        <div class="flex items-center gap-2">
          <button
            v-if="previewKind === 'image' || previewKind === 'pdf'"
            type="button"
            class="focus-ring rounded-xl bg-surface px-3 py-1.5 text-[12.5px] font-medium text-fg hover:bg-hover"
            @click="refreshMediaUrl"
          >
            刷新链接
          </button>
          <button
            v-if="target.kind === 'file'"
            type="button"
            class="focus-ring rounded-xl bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-fg hover:bg-primary-hover"
            @click="onDownload"
          >
            下载文件
          </button>
        </div>
      </div>

      <!-- Source Editor Overlay when editing writable text -->
      <div v-else-if="editingSource" class="flex min-h-0 flex-1 flex-col bg-canvas p-3">
        <textarea
          v-model="editDraft"
          v-scrollbar
          spellcheck="false"
          class="custom-scrollbar min-h-0 flex-1 resize-none rounded-xl border border-line bg-sidebar p-3 font-mono text-[12.5px] leading-relaxed text-fg outline-none focus:border-accent"
        />
      </div>

      <!-- HTML Sandboxed Preview (isolated origin via sandbox="allow-scripts" only) -->
      <template v-else-if="previewKind === 'html'">
        <iframe
          v-if="viewMode === 'preview'"
          sandbox="allow-scripts"
          referrerpolicy="no-referrer"
          :srcdoc="textContent"
          class="h-full w-full flex-1 border-0 bg-white"
          :class="resizing ? 'pointer-events-none' : ''"
          title="HTML 预览"
        />
        <div v-else v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-auto p-3.5">
          <pre
            v-if="highlightedCodeHtml"
            class="rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3] overflow-x-auto"
          ><code class="hljs" v-html="highlightedCodeHtml" /></pre>
          <pre
            v-else
            class="rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3] overflow-x-auto"
          ><code>{{ textContent }}</code></pre>
        </div>
      </template>

      <!-- Markdown Preview -->
      <template v-else-if="previewKind === 'markdown'">
        <div v-if="viewMode === 'preview'" v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto bg-canvas p-4 sm:p-5">
          <MarkdownRenderer :content="textContent" />
        </div>
        <div v-else v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-auto p-3.5">
          <pre
            v-if="highlightedCodeHtml"
            class="rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3] overflow-x-auto"
          ><code class="hljs" v-html="highlightedCodeHtml" /></pre>
          <pre
            v-else
            class="rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3] overflow-x-auto"
          ><code>{{ textContent }}</code></pre>
        </div>
      </template>

      <!-- Image Preview -->
      <div
        v-else-if="previewKind === 'image' && freshUrl"
        v-scrollbar
        class="custom-scrollbar flex min-h-0 flex-1 items-center justify-center overflow-auto bg-canvas/50 p-4"
      >
        <img
          :src="freshUrl"
          :alt="titleText"
          class="rounded-xl shadow-xs transition-all"
          :class="imageActualSize ? 'max-w-none' : 'max-h-full max-w-full object-contain'"
          @error="error = '图片预览链接已过期或加载失败'"
        />
      </div>

      <!-- PDF Preview -->
      <div v-else-if="previewKind === 'pdf' && freshUrl" class="flex min-h-0 flex-1 flex-col">
        <div class="flex items-center justify-between border-b border-line bg-canvas/60 px-3.5 py-1.5 text-[12px] text-fg-muted">
          <span>PDF 在线预览</span>
          <a
            :href="freshUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="font-medium text-accent hover:underline"
          >
            在新窗口打开 ↗
          </a>
        </div>
        <iframe
          :src="freshUrl"
          class="h-full w-full flex-1 border-0 bg-white"
          :class="resizing ? 'pointer-events-none' : ''"
          title="PDF 预览"
        />
      </div>

      <!-- CSV / TSV Table Preview & Editor -->
      <template v-else-if="previewKind === 'table'">
        <CsvTableEditor
          v-if="viewMode === 'preview'"
          :content="textContent"
          :delimiter="targetExt === '.tsv' ? '\t' : ','"
          :readonly="!canEditFile"
          :saving="saving"
          @save="saveEditedText"
        />
        <div v-else v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-auto p-3.5">
          <pre class="rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3] overflow-x-auto"><code>{{ textContent }}</code></pre>
        </div>
      </template>

      <!-- Code / JSON / YAML / XLSX / Text Preview -->
      <div v-else v-scrollbar class="custom-scrollbar flex min-h-0 flex-1 flex-col overflow-auto p-3.5">
        <p v-if="truncated" class="mb-2 rounded-lg bg-warning-weak px-2.5 py-1.5 text-[11.5px] text-warning">
          文件内容较长，预览仅展示前部片段；完整内容请点击右上角「下载」。
        </p>
        <pre
          v-if="highlightedCodeHtml"
          class="rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3] overflow-x-auto"
        ><code class="hljs" v-html="highlightedCodeHtml" /></pre>
        <pre
          v-else
          class="whitespace-pre-wrap break-words rounded-xl bg-[var(--code)] p-3.5 font-mono text-[12.5px] leading-relaxed text-[#e6edf3]"
        ><code>{{ textContent }}</code></pre>
      </div>
    </div>
  </div>
</template>
