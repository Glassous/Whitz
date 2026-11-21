<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import type { ConversationFile, FileAttachmentMeta, Message, UserReactionType, WorkspaceArtifactMeta } from "../../types";
import { useAuthStore } from "../../stores/auth";
import { useChatStore } from "../../stores/chat";
import { useFilesStore } from "../../stores/files";
import { categoryLabel, formatFileSize } from "../../lib/fileTypes";
import MarkdownRenderer from "./MarkdownRenderer.vue";
import Spinner from "../ui/Spinner.vue";

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

const props = defineProps<{ message: Message; downloadingFileId?: string | null }>();
const emit = defineEmits<{
  steps: [];
  regenerate: [assistantMessageId: string];
  edit: [userMessageId: string, content: string];
  "preview-html": [html: string];
  "preview-file": [file: ConversationFile];
  "download-file": [file: ConversationFile];
}>();

const auth = useAuthStore();
const chat = useChatStore();
const filesStore = useFilesStore();

const REACTION_OPTIONS: { key: UserReactionType; emoji: string; label: string }[] = [
  { key: "like", emoji: "👍", label: "赞" },
  { key: "love", emoji: "❤️", label: "超喜欢" },
  { key: "insightful", emoji: "💡", label: "有启发" },
  { key: "celebrate", emoji: "🎉", label: "太棒了" },
  { key: "dislike", emoji: "👎", label: "需改进" },
];
const AI_REACTION_META: Record<string, { emoji: string; label: string }> = {
  like: { emoji: "👍", label: "点赞" },
  love: { emoji: "❤️", label: "比心" },
  sparkle: { emoji: "✨", label: "亮点" },
  insightful: { emoji: "💡", label: "有洞察" },
};
const DISLIKE_REASONS = [
  { code: "inaccurate", label: "事实有误" },
  { code: "incomplete", label: "不够完整" },
  { code: "slow", label: "响应偏慢" },
  { code: "other", label: "其他" },
];

const showDislikeReasons = ref(false);
const reactionPickerOpen = ref(false);
const reactionPickerRef = ref<HTMLElement | null>(null);

const userReaction = computed(() =>
  (props.message.reactions ?? []).find((r) => r.author_type === "user") ?? null,
);
const selectedReactionMeta = computed(
  () => REACTION_OPTIONS.find((o) => o.key === userReaction.value?.reaction) ?? null,
);
const aiReaction = computed(() =>
  (props.message.reactions ?? []).find((r) => r.author_type === "assistant") ?? null,
);

function toggleReactionPicker() {
  reactionPickerOpen.value = !reactionPickerOpen.value;
}

function onDocumentPointerDown(e: PointerEvent) {
  if (!reactionPickerOpen.value) return;
  const el = reactionPickerRef.value;
  if (el && e.target instanceof Node && !el.contains(e.target)) {
    reactionPickerOpen.value = false;
  }
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (reactionPickerOpen.value && e.key === "Escape") {
    reactionPickerOpen.value = false;
  }
}

async function onSelectReaction(key: UserReactionType) {
  reactionPickerOpen.value = false;
  if (key === "dislike") {
    const alreadyDisliked = userReaction.value?.reaction === "dislike";
    await chat.reactToMessage(props.message.id, "dislike");
    showDislikeReasons.value = !alreadyDisliked;
    return;
  }
  showDislikeReasons.value = false;
  await chat.reactToMessage(props.message.id, key);
}

async function onSelectDislikeReason(code: string) {
  await chat.reactToMessage(props.message.id, "dislike", code);
  showDislikeReasons.value = false;
}

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
  if (!trimmed || chat.streaming || filesStore.hasActiveUploads) return;
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

onMounted(() => {
  document.addEventListener("pointerdown", onDocumentPointerDown);
  document.addEventListener("keydown", onDocumentKeydown);
});

onBeforeUnmount(() => {
  if (copyTimer) window.clearTimeout(copyTimer);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
  document.removeEventListener("keydown", onDocumentKeydown);
});

const isCurrent = computed(() => chat.selectedTurn?.id === props.message.id);
const isLive = computed(() => chat.streaming && chat.activeAssistantId === props.message.id);
const isFailureOrCancelled = computed(
  () => !isLive.value && (props.message.status === "failed" || props.message.status === "cancelled"),
);

const liveLabel = computed(() => {
  if (chat.stopping) return "正在停止生成…";
  if (chat.reconnecting) return "网络重连中，正在恢复进度…";
  if (chat.currentStep) {
    const step = chat.currentStep;
    return step.title ? `步骤 ${step.index}/${step.total} · ${step.title}` : `步骤 ${step.index}/${step.total}`;
  }
  if (chat.runningTool) return `正在使用 ${chat.runningTool}`;
  if (chat.waitingFirstByte) return "正在连接助理…";
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
            :disabled="!editText.trim() || chat.streaming || filesStore.hasActiveUploads"
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

      <!-- AI Positive Reaction Badge on User Message -->
      <div
        v-if="!editing && aiReaction"
        class="mt-1 inline-flex items-center gap-1 rounded-full border border-line bg-sidebar/90 px-2 py-0.5 text-[11.5px] text-fg-muted shadow-2xs"
        :title="aiReaction.comment || `${auth.user?.assistant_name || 'Whitz'} 给了你一个正向回应`"
      >
        <span>{{ AI_REACTION_META[aiReaction.reaction]?.emoji ?? "👍" }}</span>
        <span>{{ auth.user?.assistant_name || "Whitz" }} · {{ AI_REACTION_META[aiReaction.reaction]?.label ?? "点赞" }}</span>
        <span v-if="aiReaction.comment" class="max-w-[160px] truncate text-fg-faint">· {{ aiReaction.comment }}</span>
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
      <Spinner v-if="isLive" :size="13" class="shrink-0 text-accent" />
      <span class="truncate">{{ isLive ? liveLabel : "步骤查看" }}</span>
      <span v-if="!isLive && stepsCount" class="shrink-0 tabular-nums opacity-80">· {{ stepsCount }}</span>
      <svg class="h-3.5 w-3.5 shrink-0 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
      </svg>
    </button>

    <div
      v-if="isLive && !message.content.trim()"
      class="flex items-center gap-2 py-2 text-[13.5px] text-fg-faint"
      role="status"
      aria-live="polite"
    >
      <span class="inline-flex items-center gap-1" aria-hidden="true">
        <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent/80" />
        <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent/60 [animation-delay:150ms]" />
        <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent/40 [animation-delay:300ms]" />
      </span>
      <span>{{ chat.reconnecting ? "正在恢复实时输出…" : chat.waitingFirstByte ? "助理已接收请求，正在准备回复…" : "正在组织回答…" }}</span>
    </div>

    <MarkdownRenderer v-else :content="message.content" @preview-html="emit('preview-html', $event)" />

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
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="downloadingFileId === file.id"
            aria-label="下载文件"
            title="下载"
            @click="emit('download-file', file)"
          >
            <Spinner v-if="downloadingFileId === file.id" :size="15" />
            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
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
        :disabled="chat.streaming || filesStore.hasActiveUploads"
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
        :disabled="chat.streaming || filesStore.hasActiveUploads"
        aria-label="重新生成"
        title="重新生成"
        @click="emit('regenerate', message.id)"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 12a9 9 0 0115.3-6.4L21 8M21 3v5h-5M21 12a9 9 0 01-15.3 6.4L3 16M3 21v-5h5" />
        </svg>
        <span>重新生成</span>
      </button>

      <!-- Emoji Reaction Trigger + Right-Expanding Picker Card -->
      <div ref="reactionPickerRef" class="relative inline-flex items-center">
        <button
          type="button"
          class="focus-ring inline-flex h-7.5 items-center justify-center gap-1 rounded-lg px-2 text-[12px] transition-colors"
          :class="
            selectedReactionMeta
              ? selectedReactionMeta.key === 'dislike'
                ? 'bg-danger-weak text-danger font-medium'
                : 'bg-accent-weak text-accent font-medium'
              : reactionPickerOpen
                ? 'bg-hover text-fg'
                : 'text-fg-faint hover:bg-hover hover:text-fg'
          "
          :aria-expanded="reactionPickerOpen"
          :aria-label="selectedReactionMeta ? `已评价：${selectedReactionMeta.label}` : '表情评价'"
          :title="selectedReactionMeta ? `已评价：${selectedReactionMeta.label}（点击切换或取消）` : '表情评价'"
          @click="toggleReactionPicker"
        >
          <span v-if="selectedReactionMeta" class="text-[14px] leading-none">{{ selectedReactionMeta.emoji }}</span>
          <svg
            v-else
            class="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.85"
          >
            <circle cx="12" cy="12" r="9" />
            <path stroke-linecap="round" d="M8.5 14.5s1.3 2 3.5 2 3.5-2 3.5-2" />
            <circle cx="9.25" cy="9.75" r="0.75" fill="currentColor" stroke="none" />
            <circle cx="14.75" cy="9.75" r="0.75" fill="currentColor" stroke="none" />
          </svg>
        </button>

        <Transition
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="-translate-x-1.5 scale-95 opacity-0"
          enter-to-class="translate-x-0 scale-100 opacity-100"
          leave-active-class="transition duration-100 ease-in"
          leave-from-class="translate-x-0 scale-100 opacity-100"
          leave-to-class="-translate-x-1.5 scale-95 opacity-0"
        >
          <div
            v-if="reactionPickerOpen"
            role="menu"
            aria-label="选择消息评价表情"
            class="absolute left-full top-1/2 z-20 ml-1.5 flex -translate-y-1/2 items-center gap-0.5 rounded-2xl border border-line bg-canvas/95 px-1.5 py-1 shadow-lg backdrop-blur-md"
          >
            <button
              v-for="opt in REACTION_OPTIONS"
              :key="opt.key"
              type="button"
              role="menuitem"
              class="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-xl text-[15px] leading-none transition-transform hover:scale-110"
              :class="
                userReaction?.reaction === opt.key
                  ? opt.key === 'dislike'
                    ? 'bg-danger-weak ring-1 ring-danger/30'
                    : 'bg-accent-weak ring-1 ring-accent/30'
                  : 'hover:bg-hover'
              "
              :title="opt.label"
              :aria-label="opt.label"
              :aria-pressed="userReaction?.reaction === opt.key"
              @click="onSelectReaction(opt.key)"
            >
              <span>{{ opt.emoji }}</span>
            </button>
          </div>
        </Transition>
      </div>
    </div>

    <!-- Optional Quick Reason Chips on Dislike -->
    <div
      v-if="showDislikeReasons && userReaction?.reaction === 'dislike'"
      class="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11.5px]"
    >
      <span class="text-fg-faint">反馈原因（可选）：</span>
      <button
        v-for="r in DISLIKE_REASONS"
        :key="r.code"
        type="button"
        class="focus-ring rounded-full border border-line bg-surface px-2.5 py-0.5 text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
        :class="userReaction?.reason_code === r.code ? 'border-danger/50 bg-danger-weak text-danger' : ''"
        @click="onSelectDislikeReason(r.code)"
      >
        {{ r.label }}
      </button>
    </div>
  </div>
</template>
