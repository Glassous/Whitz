<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from "vue";
import type { ConversationFile, FileAttachmentMeta, Message, WorkspaceArtifactMeta } from "../../types";
import { useChatStore } from "../../stores/chat";
import { useFilesStore } from "../../stores/files";
import { categoryLabel, formatFileSize } from "../../lib/fileTypes";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

const props = defineProps<{ message: Message }>();
const emit = defineEmits<{
  steps: [];
  regenerate: [assistantMessageId: string];
  edit: [userMessageId: string, content: string];
  "preview-html": [html: string];
  "preview-file": [file: ConversationFile];
  "download-file": [file: ConversationFile];
}>();

const chat = useChatStore();
const filesStore = useFilesStore();

const copied = ref(false);
let copyTimer: number | null = null;

const editing = ref(false);
const editText = ref("");
const editTextareaRef = ref<HTMLTextAreaElement | null>(null);

const failedImgIds = ref<Set<string>>(new Set());
const refreshedImgIds = new Set<string>();

async function copyContent() {
  const text = props.message.content;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
  copied.value = true;
  if (copyTimer) window.clearTimeout(copyTimer);
  copyTimer = window.setTimeout(() => {
    copied.value = false;
    copyTimer = null;
  }, 2000);
}

function startEdit() {
  if (chat.streaming) return;
  editText.value = props.message.content;
  editing.value = true;
  void nextTick(() => {
    editTextareaRef.value?.focus();
    const len = editText.value.length;
    editTextareaRef.value?.setSelectionRange(len, len);
  });
}

function cancelEdit() {
  editing.value = false;
  editText.value = "";
}

function submitEdit() {
  const trimmed = editText.value.trim();
  if (!trimmed || chat.streaming) return;
  editing.value = false;
  emit("edit", props.message.id, trimmed);
}

function onEditKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") {
    e.preventDefault();
    cancelEdit();
  } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing) {
    e.preventDefault();
    submitEdit();
  }
}

onBeforeUnmount(() => {
  if (copyTimer) window.clearTimeout(copyTimer);
});

const isCurrent = computed(() => chat.selectedTurn?.id === props.message.id);
const isLive = computed(() => chat.streaming && chat.activeAssistantId === props.message.id);
const isFailureOrCancelled = computed(
  () => !isLive.value && (props.message.status === "failed" || props.message.status === "cancelled"),
);

const liveLabel = computed(() => {
  if (chat.currentStep) {
    const step = chat.currentStep;
    return step.title ? `步骤 ${step.index}/${step.total} · ${step.title}` : `步骤 ${step.index}/${step.total}`;
  }
  if (chat.runningTool) return `正在使用 ${chat.runningTool}`;
  const items = chat.plan?.items ?? [];
  if (items.length && items.every((item) => item.status === "completed")) return "正在生成回答…";
  return "正在思考…";
});

const stepsCount = computed(() => {
  const plan = isCurrent.value ? chat.viewPlan : props.message.tool_payload?.plan;
  if (plan?.items?.length) return plan.items.length;
  const blocks = isCurrent.value ? chat.viewReasoning : props.message.tool_payload?.reasoning ?? [];
  const keys = new Set(
    blocks.filter((b) => b.step != null).map((b) => b.step_id ?? `step-${b.step}`),
  );
  return keys.size;
});

function resolveAttachmentFile(att: FileAttachmentMeta): ConversationFile {
  const found = filesStore.files.find((f) => f.id === att.id);
  if (found) return found;
  const raw = att as FileAttachmentMeta & { preview_url?: string | null; thumb_url?: string | null; preview_expires_at?: string | null };
  return {
    id: att.id,
    conversation_id: chat.convId,
    filename: att.filename,
    ext: att.ext,
    mime_type: "",
    category: att.category,
    size_bytes: att.size_bytes,
    status: "ready",
    source: "user",
    is_global: false,
    preview_url: raw.preview_url ?? null,
    thumb_url: raw.thumb_url ?? null,
    preview_expires_at: raw.preview_expires_at ?? null,
    created_at: props.message.created_at,
    updated_at: props.message.created_at,
  };
}

function resolveArtifactFile(art: WorkspaceArtifactMeta): ConversationFile {
  const found = filesStore.files.find((f) => f.id === art.id);
  if (found) {
    return {
      ...found,
      preview_url: found.preview_url || art.preview_url || null,
      thumb_url: found.thumb_url || art.thumb_url || null,
      preview_expires_at: found.preview_expires_at || art.preview_expires_at || null,
    };
  }
  return {
    id: art.id,
    conversation_id: chat.convId,
    filename: art.filename,
    ext: art.ext,
    mime_type: art.mime_type ?? "",
    category: art.category,
    size_bytes: art.size_bytes,
    status: "ready",
    source: art.source ?? "assistant",
    is_global: Boolean(art.is_global),
    message_id: art.message_id ?? props.message.id,
    preview_url: art.preview_url ?? null,
    thumb_url: art.thumb_url ?? null,
    preview_expires_at: art.preview_expires_at ?? null,
    created_at: props.message.created_at,
    updated_at: props.message.created_at,
  };
}

function isImageFile(file: { category: string; ext?: string }): boolean {
  return file.category === "image" || IMAGE_EXTS.has((file.ext || "").toLowerCase());
}

function imageThumbUrl(file: ConversationFile): string | null {
  if (!isImageFile(file) || failedImgIds.value.has(file.id)) return null;
  return file.thumb_url || file.preview_url || null;
}

async function onThumbError(file: ConversationFile) {
  if (!refreshedImgIds.has(file.id)) {
    refreshedImgIds.add(file.id);
    try {
      const fresh = await filesStore.ensureFreshUrl(file, true);
      if (fresh) return;
    } catch {
      /* fall back below */
    }
  }
  const next = new Set(failedImgIds.value);
  next.add(file.id);
  failedImgIds.value = next;
}

const resolvedAttachments = computed(() =>
  (props.message.tool_payload?.attachments ?? []).map((att) => resolveAttachmentFile(att)),
);

const resolvedArtifacts = computed(() =>
  (props.message.tool_payload?.artifacts ?? []).map((art) => resolveArtifactFile(art)),
);
</script>

<template>
  <div v-if="message.role === 'user'" class="flex justify-end">
    <div class="group/user flex max-w-[85%] flex-col items-end sm:max-w-[75%]">
      <!-- Selected skill badges -->
      <div
        v-if="message.tool_payload?.skills?.length"
        class="mb-1.5 flex flex-wrap justify-end gap-1.5"
      >
        <span
          v-for="skillName in message.tool_payload.skills"
          :key="skillName"
          class="inline-flex items-center gap-1 rounded-full bg-accent-weak/85 px-2.5 py-0.5 text-[11.5px] font-medium text-accent"
        >
          <svg class="h-3 w-3 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.6l-1.7-4.6L6 9.3l4.3-1.7L12 3z" />
          </svg>
          <span>{{ skillName }}</span>
        </span>
      </div>

      <!-- Attached files & image thumbnails -->
      <div
        v-if="resolvedAttachments.length"
        class="mb-1.5 flex flex-wrap justify-end gap-1.5"
      >
        <button
          v-for="file in resolvedAttachments"
          :key="file.id"
          type="button"
          class="focus-ring inline-flex max-w-[240px] items-center gap-2 rounded-xl bg-surface px-2.5 py-1.5 text-left text-[12px] text-fg-muted transition-colors hover:bg-hover"
          :title="`${file.filename} (${formatFileSize(file.size_bytes)}) — 点击预览`"
          @click="emit('preview-file', file)"
        >
          <img
            v-if="imageThumbUrl(file)"
            :src="imageThumbUrl(file)!"
            :alt="file.filename"
            class="h-10 w-10 shrink-0 rounded-lg bg-canvas object-cover"
            @error="onThumbError(file)"
          />
          <svg v-else class="h-3.5 w-3.5 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M14 2v6h6" />
          </svg>
          <span class="min-w-0 flex-1 truncate font-medium text-fg">{{ file.filename }}</span>
          <span class="shrink-0 text-[11px] text-fg-faint">{{ categoryLabel(file.category, file.ext) }}</span>
        </button>
      </div>

      <!-- Inline Edit Mode -->
      <div
        v-if="editing"
        class="w-full min-w-[min(22rem,75dvw)] rounded-[22px] bg-surface p-3 shadow-xs"
      >
        <textarea
          ref="editTextareaRef"
          v-model="editText"
          v-scrollbar
          rows="3"
          class="custom-scrollbar w-full resize-y rounded-xl bg-canvas px-3 py-2 text-[14.5px] leading-relaxed text-fg outline-none focus:ring-2 focus:ring-accent/40"
          placeholder="修改消息内容…"
          @keydown="onEditKeydown"
        />
        <div class="mt-2 flex items-center justify-end gap-2">
          <button
            type="button"
            class="focus-ring rounded-full px-3 py-1.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="cancelEdit"
          >
            取消
          </button>
          <button
            type="button"
            class="focus-ring rounded-full bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-fg transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="!editText.trim() || chat.streaming"
            @click="submitEdit"
          >
            保存并重发
          </button>
        </div>
      </div>

      <!-- Normal User Message Bubble -->
      <div
        v-else
        class="w-fit max-w-full whitespace-pre-wrap rounded-[22px] bg-surface px-4 py-2.5 text-[15px] leading-relaxed text-fg"
      >
        {{ message.content }}
      </div>

      <div
        v-if="!editing"
        class="flex items-center justify-end gap-0.5 pt-1.5 transition-opacity duration-150"
        :class="
          copied
            ? 'pointer-events-auto opacity-100'
            : 'pointer-events-none opacity-0 group-hover/user:pointer-events-auto group-hover/user:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100'
        "
      >
        <button
          type="button"
          class="focus-ring flex h-7 items-center gap-1 rounded-lg px-1.5 text-[12px] text-fg-faint transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="chat.streaming"
          aria-label="编辑并重发"
          title="编辑并重发"
          @click="startEdit"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11 4H4v16h16v-7M18.5 2.5a2.1 2.1 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
          <span>编辑</span>
        </button>

        <button
          type="button"
          class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          :aria-label="copied ? '已复制' : '复制消息'"
          :title="copied ? '已复制' : '复制'"
          @click="copyContent"
        >
          <Transition
            mode="out-in"
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="scale-75 opacity-0"
            enter-to-class="scale-100 opacity-100"
            leave-active-class="transition duration-100 ease-in"
            leave-from-class="scale-100 opacity-100"
            leave-to-class="scale-75 opacity-0"
          >
            <svg
              v-if="copied"
              key="check"
              class="h-4 w-4 text-success"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            <svg
              v-else
              key="copy"
              class="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
            >
              <rect x="9" y="9" width="11" height="11" rx="2.2" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
          </Transition>
        </button>
      </div>
    </div>
  </div>

  <div v-else class="min-w-0">
    <button
      type="button"
      class="mb-2.5 inline-flex min-h-8 max-w-full items-center gap-2 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors"
      :class="
        isCurrent
          ? 'bg-accent-weak/85 text-accent'
          : 'bg-surface/80 text-fg-muted hover:bg-surface hover:text-fg'
      "
      :aria-pressed="isCurrent"
      @click="emit('steps')"
    >
      <span class="truncate">{{ isLive ? liveLabel : "步骤查看" }}</span>
      <span v-if="!isLive && stepsCount" class="shrink-0 tabular-nums opacity-80">· {{ stepsCount }}</span>
      <svg class="h-3.5 w-3.5 shrink-0 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
      </svg>
    </button>

    <MarkdownRenderer :content="message.content" @preview-html="emit('preview-html', $event)" />

    <!-- AI Generated Workspace Artifact Cards -->
    <div v-if="resolvedArtifacts.length" class="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
      <div
        v-for="file in resolvedArtifacts"
        :key="file.id"
        class="group/artifact flex items-center gap-3 rounded-2xl border border-line bg-sidebar/80 p-2.5 transition-colors hover:border-line-strong hover:bg-surface/90"
      >
        <button
          type="button"
          class="focus-ring flex min-w-0 flex-1 items-center gap-2.5 text-left"
          @click="emit('preview-file', file)"
        >
          <img
            v-if="imageThumbUrl(file)"
            :src="imageThumbUrl(file)!"
            :alt="file.filename"
            class="h-11 w-11 shrink-0 rounded-xl bg-canvas object-cover"
            @error="onThumbError(file)"
          />
          <span
            v-else
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-canvas text-[11px] font-semibold text-fg-muted"
          >
            {{ categoryLabel(file.category, file.ext) }}
          </span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-[13.5px] font-medium text-fg" :title="file.filename">
              {{ file.filename }}
            </span>
            <span class="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-fg-faint">
              <span class="rounded bg-canvas px-1.5 py-0.5 text-[10.5px] font-medium text-fg-muted">
                {{ categoryLabel(file.category, file.ext) }}
              </span>
              <span class="tabular-nums">{{ formatFileSize(file.size_bytes) }}</span>
            </span>
          </span>
        </button>

        <div class="flex shrink-0 items-center gap-1">
          <button
            type="button"
            class="focus-ring rounded-lg bg-canvas px-2.5 py-1.5 text-[12px] font-medium text-fg transition-colors hover:bg-hover"
            @click="emit('preview-file', file)"
          >
            在线预览
          </button>
          <button
            type="button"
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            aria-label="下载文件"
            title="下载"
            @click="emit('download-file', file)"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Failure / Cancelled Status + Prominent Retry -->
    <div v-if="isFailureOrCancelled" class="mt-2.5 flex flex-wrap items-center gap-2.5">
      <p class="text-[12.5px]" :class="message.status === 'failed' ? 'text-danger' : 'text-fg-faint'">
        {{ message.status === "failed" ? "回复失败，请重试。" : "已停止生成" }}
      </p>
      <button
        type="button"
        class="focus-ring inline-flex items-center gap-1.5 rounded-full bg-primary px-3 py-1 text-[12px] font-medium text-primary-fg transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="chat.streaming"
        @click="emit('regenerate', message.id)"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 12a9 9 0 0115.3-6.4L21 8M21 3v5h-5M21 12a9 9 0 01-15.3 6.4L3 16M3 21v-5h5" />
        </svg>
        <span>重试</span>
      </button>
    </div>

    <!-- Assistant Action Bar -->
    <div v-if="!isLive && (message.content.trim() || isFailureOrCancelled)" class="mt-2 flex items-center gap-1">
      <button
        v-if="message.content.trim()"
        type="button"
        class="focus-ring flex h-7.5 w-7.5 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
        :aria-label="copied ? '已复制' : '复制回复'"
        :title="copied ? '已复制' : '复制'"
        @click="copyContent"
      >
        <Transition
          mode="out-in"
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="scale-75 opacity-0"
          enter-to-class="scale-100 opacity-100"
          leave-active-class="transition duration-100 ease-in"
          leave-from-class="scale-100 opacity-100"
          leave-to-class="scale-75 opacity-0"
        >
          <svg
            v-if="copied"
            key="check"
            class="h-4 w-4 text-success"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          <svg
            v-else
            key="copy"
            class="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.85"
          >
            <rect x="9" y="9" width="11" height="11" rx="2.2" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
        </Transition>
      </button>

      <button
        type="button"
        class="focus-ring inline-flex h-7.5 items-center gap-1 rounded-lg px-2 text-[12px] font-medium text-fg-faint transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-45"
        :disabled="chat.streaming"
        aria-label="重新生成"
        title="重新生成"
        @click="emit('regenerate', message.id)"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 12a9 9 0 0115.3-6.4L21 8M21 3v5h-5M21 12a9 9 0 01-15.3 6.4L3 16M3 21v-5h5" />
        </svg>
        <span>重新生成</span>
      </button>
    </div>
  </div>
</template>
