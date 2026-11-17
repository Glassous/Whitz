<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { ACCEPT_ATTR, SUPPORTED_TYPES_SUMMARY, categoryLabel, formatFileSize, validateDragItems } from "../../lib/fileTypes";
import type { ConversationFile, UploadTask } from "../../types";

const props = defineProps<{
  streaming: boolean;
  disabled?: boolean;
  uploading?: boolean;
  uploads?: UploadTask[];
  attachedFiles?: ConversationFile[];
}>();

const emit = defineEmits<{
  send: [string];
  stop: [];
  upload: [files: FileList, dataTransfer?: DataTransfer | null];
  "cancel-upload": [localId: string];
  "dismiss-upload": [localId: string];
  "detach-file": [fileId: string];
}>();

const NORMAL_MAX_HEIGHT = 160;

const text = ref("");
const area = ref<HTMLTextAreaElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const canExpand = ref(false);
const expanded = ref(false);

const dragDepth = ref(0);
const dragValid = ref(true);
const dragReason = ref("");

const isDragging = computed(() => dragDepth.value > 0);
const hasChips = computed(() => (props.uploads?.length ?? 0) > 0 || (props.attachedFiles?.length ?? 0) > 0);
const sendLockedByUpload = computed(() => !!props.uploading && !props.streaming);
const canSubmit = computed(() => !!text.value.trim() && !props.streaming && !props.disabled && !props.uploading);

const uploadStatusAnnouncement = computed(() => {
  const active = props.uploads?.filter((u) => u.status !== "error") ?? [];
  if (active.length) return `正在上传 ${active.length} 个文件，上传期间发送按钮已锁定`;
  return "";
});

function updateExpandState() {
  const el = area.value;
  if (!el) return;
  canExpand.value = el.scrollHeight > NORMAL_MAX_HEIGHT;
  if (!canExpand.value && expanded.value) {
    expanded.value = false;
  }
}

function toggleExpand() {
  if (!canExpand.value && !expanded.value) return;
  expanded.value = !expanded.value;
  area.value?.focus();
}

function submit() {
  const value = text.value.trim();
  if (!value || props.streaming || props.disabled || props.uploading) return;
  emit("send", value);
  text.value = "";
  expanded.value = false;
  canExpand.value = false;
  void nextTick(updateExpandState);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  }
}

function openFilePicker() {
  if (props.disabled) return;
  fileInput.value?.click();
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files.length > 0) {
    emit("upload", input.files, null);
  }
  input.value = "";
}

function onDragEnter(e: DragEvent) {
  const check = validateDragItems(e.dataTransfer);
  if (!check.hasFiles) return;
  e.preventDefault();
  dragDepth.value += 1;
  dragValid.value = check.valid;
  dragReason.value = check.reason ?? "";
}

function onDragOver(e: DragEvent) {
  const check = validateDragItems(e.dataTransfer);
  if (!check.hasFiles) return;
  e.preventDefault();
  dragValid.value = check.valid;
  dragReason.value = check.reason ?? "";
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = check.valid && !props.disabled ? "copy" : "none";
  }
}

function onDragLeave(e: DragEvent) {
  if (dragDepth.value <= 0) return;
  const check = validateDragItems(e.dataTransfer);
  if (!check.hasFiles && dragDepth.value === 0) return;
  dragDepth.value = Math.max(0, dragDepth.value - 1);
  if (dragDepth.value === 0) {
    dragValid.value = true;
    dragReason.value = "";
  }
}

function onDrop(e: DragEvent) {
  const hadFiles = e.dataTransfer?.types?.includes("Files") || (e.dataTransfer?.files?.length ?? 0) > 0;
  dragDepth.value = 0;
  dragValid.value = true;
  dragReason.value = "";
  if (!hadFiles) return;
  e.preventDefault();
  if (props.disabled) return;
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    emit("upload", e.dataTransfer.files, e.dataTransfer);
  }
}

function uploadLabel(u: UploadTask): string {
  if (u.status === "signing") return "签名中…";
  if (u.status === "uploading") return `${u.progress}%`;
  if (u.status === "completing") return "确认中…";
  return "上传失败";
}

watch(text, () => {
  void nextTick(updateExpandState);
});

onMounted(() => {
  void nextTick(updateExpandState);
});
</script>

<template>
  <div
    class="relative"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <input
      ref="fileInput"
      type="file"
      multiple
      :accept="ACCEPT_ATTR"
      class="sr-only"
      @change="onFileChange"
    />

    <span class="sr-only" role="status" aria-live="polite">{{ uploadStatusAnnouncement }}</span>

    <div
      class="relative flex flex-col rounded-[26px] bg-surface px-3.5 pb-2.5 pt-3 transition-colors focus-within:bg-hover/70"
      :class="isDragging ? (dragValid ? 'ring-2 ring-accent/60' : 'ring-2 ring-danger/70') : ''"
    >
      <!-- Uploading & newly attached chips -->
      <div v-if="hasChips" class="mb-2 flex flex-wrap gap-1.5 px-1">
        <div
          v-for="u in uploads"
          :key="u.localId"
          class="flex max-w-[240px] flex-col gap-1 rounded-xl px-2.5 py-1.5 text-[12px]"
          :class="u.status === 'error' ? 'bg-danger-weak text-danger' : 'bg-canvas/85 text-fg'"
        >
          <div class="flex items-center gap-1.5">
            <span class="shrink-0 rounded bg-surface px-1 py-0.5 text-[10.5px] font-medium text-fg-muted">
              {{ categoryLabel(u.category, u.ext) }}
            </span>
            <span class="min-w-0 flex-1 truncate font-medium" :title="u.filename">{{ u.filename }}</span>
            <span class="shrink-0 tabular-nums text-[11px] opacity-80">{{ uploadLabel(u) }}</span>
            <button
              type="button"
              class="focus-ring flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              :aria-label="u.status === 'error' ? '关闭错误项' : '取消上传'"
              @click="u.status === 'error' ? emit('dismiss-upload', u.localId) : emit('cancel-upload', u.localId)"
            >
              <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <progress
            v-if="u.status !== 'error'"
            class="upload-progress h-1 w-full"
            :value="u.status === 'uploading' ? u.progress : undefined"
            max="100"
            :aria-label="`${u.filename} 上传进度`"
          />
          <p v-if="u.status === 'error' && u.error" class="truncate text-[11px]" :title="u.error">{{ u.error }}</p>
        </div>

        <div
          v-for="f in attachedFiles"
          :key="f.id"
          class="inline-flex max-w-[240px] items-center gap-1.5 rounded-xl bg-canvas/85 px-2.5 py-1.5 text-[12px] text-fg"
          :title="`${f.filename} (${formatFileSize(f.size_bytes)})`"
        >
          <span class="shrink-0 rounded bg-surface px-1 py-0.5 text-[10.5px] font-medium text-fg-muted">
            {{ categoryLabel(f.category, f.ext) }}
          </span>
          <span class="min-w-0 flex-1 truncate font-medium">{{ f.filename }}</span>
          <span class="shrink-0 text-[11px] text-fg-faint">{{ formatFileSize(f.size_bytes) }}</span>
          <button
            type="button"
            class="focus-ring flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-fg"
            aria-label="从本条消息移除标签（文件仍保留在工作区）"
            title="从本条消息移除标签（文件仍保留在工作区）"
            @click="emit('detach-file', f.id)"
          >
            <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Row 1: Native field-sizing: content auto-resizing textarea -->
      <div class="relative">
        <textarea
          ref="area"
          v-model="text"
          v-scrollbar
          rows="1"
          :disabled="disabled"
          :placeholder="
            disabled
              ? '助理正在初始化，请稍候…'
              : uploading
                ? '文件正在直传 COS，上传完成后即可发送…'
                : '给 Whitz 发送消息，或拖拽文件到此处上传…'
          "
          class="chat-textarea custom-scrollbar block resize-none bg-transparent px-1 py-0.5 text-[15px] leading-relaxed text-fg outline-none placeholder:text-fg-faint disabled:cursor-not-allowed"
          :class="{ 'is-expanded': expanded }"
          @keydown="onKeydown"
        />
      </div>

      <!-- Row 2: Action bar (left upload button + right expand/collapse & send/stop) -->
      <div class="mt-2 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="focus-ring flex h-9 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="disabled"
            aria-label="上传文件到对话工作区"
            :title="`上传文件到当前对话工作区（${SUPPORTED_TYPES_SUMMARY}）`"
            @click="openFilePicker"
          >
            <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M21.44 11.05l-8.49 8.49a5.5 5.5 0 01-7.78-7.78l8.49-8.49a3.5 3.5 0 114.95 4.95l-8.49 8.49a1.5 1.5 0 01-2.12-2.12l7.78-7.78"
              />
            </svg>
            <span class="hidden sm:inline">上传文件</span>
          </button>

          <span v-if="sendLockedByUpload" class="text-[12px] text-fg-faint">
            上传中，完成后可发送…
          </span>
        </div>

        <div class="flex items-center gap-1.5">
          <Transition
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="scale-75 opacity-0"
            enter-to-class="scale-100 opacity-100"
            leave-active-class="transition duration-100 ease-in"
            leave-from-class="scale-100 opacity-100"
            leave-to-class="scale-75 opacity-0"
          >
            <button
              v-if="canExpand || expanded"
              type="button"
              class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              :aria-label="expanded ? '收起输入框' : '展开输入框'"
              :title="expanded ? '收起输入框' : '加大输入框'"
              @click="toggleExpand"
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
                  v-if="expanded"
                  key="collapse"
                  class="h-4.5 w-4.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7" />
                </svg>
                <svg
                  v-else
                  key="expand"
                  class="h-4.5 w-4.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
                </svg>
              </Transition>
            </button>
          </Transition>

          <button
            v-if="streaming"
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-canvas text-fg transition-colors hover:bg-hover"
            aria-label="停止生成"
            title="停止生成"
            @click="emit('stop')"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="6" width="12" height="12" rx="2.5" />
            </svg>
          </button>
          <button
            v-else
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-fg transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-hover disabled:text-fg-faint"
            :disabled="!canSubmit"
            :aria-label="sendLockedByUpload ? '文件上传中，暂不可发送' : '发送'"
            :title="sendLockedByUpload ? '文件上传中，请等待全部上传完成后发送' : '发送'"
            @click="submit"
          >
            <svg
              v-if="sendLockedByUpload"
              class="h-4 w-4 animate-spin"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
            >
              <circle cx="12" cy="12" r="9" class="opacity-25" />
              <path stroke-linecap="round" d="M12 3a9 9 0 019 9" />
            </svg>
            <svg v-else class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Full-area Drag Overlay -->
      <Transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition duration-100 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="isDragging"
          class="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center rounded-[26px] border-2 border-dashed px-4 text-center backdrop-blur-[2px]"
          :class="
            dragValid
              ? 'border-accent bg-surface/92 text-fg'
              : 'border-danger bg-danger-weak/92 text-danger'
          "
        >
          <p class="text-[13.5px] font-medium">
            {{ dragValid ? "松开以上传到当前对话工作区" : "不支持的文件类型" }}
          </p>
          <p class="mt-0.5 max-w-md truncate text-[12px] opacity-80">
            {{ dragValid ? SUPPORTED_TYPES_SUMMARY : dragReason }}
          </p>
        </div>
      </Transition>
    </div>
  </div>
</template>
