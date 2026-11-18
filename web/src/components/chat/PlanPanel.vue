<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import {
  ACCEPT_ATTR,
  MAX_FILES_PER_CONVERSATION,
  SUPPORTED_TYPES_SUMMARY,
  categoryLabel,
  formatFileSize,
  validateDragItems,
} from "../../lib/fileTypes";
import type { ConversationFile, Plan, PlanItem, ReasoningBlock, TaskPanelTab, UploadTask } from "../../types";
import Spinner from "../ui/Spinner.vue";
import ReasoningEntry from "./ReasoningEntry.vue";

const props = defineProps<{
  plan: Plan | null;
  reasoning: ReasoningBlock[];
  streaming: boolean;
  currentStep: { index: number; total: number; title: string } | null;
  runningTool: string | null;
  turnKey: string;
  activeTab?: TaskPanelTab;
  files: ConversationFile[];
  uploads: UploadTask[];
  filesLoading?: boolean;
  uploadDisabled?: boolean;
  hideHeader?: boolean;
}>();

const emit = defineEmits<{
  "update:activeTab": [TaskPanelTab];
  upload: [files: FileList, dataTransfer?: DataTransfer | null];
  "cancel-upload": [localId: string];
  "dismiss-upload": [localId: string];
  "delete-file": [fileId: string];
  "download-file": [file: ConversationFile];
}>();

const fileInput = ref<HTMLInputElement | null>(null);
const splitContainerRef = ref<HTMLElement | null>(null);
const stepsRatio = ref(56);
const draggingSplit = ref(false);
let splitStartY = 0;
let splitStartRatio = 56;

function onSplitPointerDown(e: PointerEvent) {
  const container = splitContainerRef.value;
  if (!container) return;
  const target = e.currentTarget as HTMLElement;
  target.setPointerCapture(e.pointerId);
  draggingSplit.value = true;
  splitStartY = e.clientY;
  splitStartRatio = stepsRatio.value;
}

function onSplitPointerMove(e: PointerEvent) {
  if (!draggingSplit.value || !splitContainerRef.value) return;
  const totalH = splitContainerRef.value.clientHeight;
  if (totalH <= 0) return;
  const deltaPct = ((e.clientY - splitStartY) / totalH) * 100;
  stepsRatio.value = Math.round(Math.max(20, Math.min(80, splitStartRatio + deltaPct)) * 10) / 10;
}

function onSplitPointerUp(e: PointerEvent) {
  if (!draggingSplit.value) return;
  draggingSplit.value = false;
  const target = e.currentTarget as HTMLElement;
  if (target.hasPointerCapture(e.pointerId)) {
    target.releasePointerCapture(e.pointerId);
  }
}

function onSplitKeydown(e: KeyboardEvent) {
  if (e.key === "ArrowUp") {
    e.preventDefault();
    stepsRatio.value = Math.max(20, stepsRatio.value - 5);
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    stepsRatio.value = Math.min(80, stepsRatio.value + 5);
  }
}

const dragDepth = ref(0);
const dragValid = ref(true);
const dragReason = ref("");
const isDragging = computed(() => dragDepth.value > 0);

const deletingId = ref<string | null>(null);
const downloadingId = ref<string | null>(null);

function openFilePicker() {
  if (props.uploadDisabled) return;
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
    e.dataTransfer.dropEffect = check.valid && !props.uploadDisabled ? "copy" : "none";
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
  if (props.uploadDisabled) return;
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    emit("upload", e.dataTransfer.files, e.dataTransfer);
  }
}

function onDeleteClick(fileId: string) {
  deletingId.value = fileId;
  emit("delete-file", fileId);
  window.setTimeout(() => {
    if (deletingId.value === fileId) deletingId.value = null;
  }, 800);
}

function onDownloadClick(file: ConversationFile) {
  downloadingId.value = file.id;
  emit("download-file", file);
  window.setTimeout(() => {
    if (downloadingId.value === file.id) downloadingId.value = null;
  }, 800);
}

const items = computed<PlanItem[]>(() => props.plan?.items ?? []);

function blocksFor(item: PlanItem, index: number): ReasoningBlock[] {
  return props.reasoning.filter((b) => {
    if (b.step == null) return false;
    if (b.step_id != null && item.id != null) return b.step_id === String(item.id);
    return b.step === index;
  });
}

const steps = computed(() =>
  items.value.map((item, idx) => ({
    item,
    index: idx + 1,
    blocks: blocksFor(item, idx + 1),
  })),
);

const toggledSteps = ref<Record<string, boolean>>({});

function stepKey(step: { item: PlanItem; index: number }): string {
  return step.item.id != null ? String(step.item.id) : `idx-${step.index}`;
}

function stepOpen(step: { item: PlanItem; index: number }): boolean {
  return toggledSteps.value[stepKey(step)] ?? step.item.status === "in_progress";
}

function toggleStep(step: { item: PlanItem; index: number }) {
  toggledSteps.value = { ...toggledSteps.value, [stepKey(step)]: !stepOpen(step) };
}

function stepMeta(step: { blocks: ReasoningBlock[] }): string {
  const calls = step.blocks.length;
  const tools = step.blocks.reduce((sum, b) => sum + (b.tools?.length ?? 0), 0);
  return [calls ? `${calls} 段思考` : "", tools ? `${tools} 个操作` : ""].filter(Boolean).join(" · ");
}

watch(
  () => props.streaming,
  (val, old) => {
    if (val && !old) toggledSteps.value = {};
  },
);

watch(
  () => props.turnKey,
  async () => {
    toggledSteps.value = {};
    await nextTick();
    if (scrollEl.value) scrollEl.value.scrollTop = 0;
  },
);

const matchedBlocks = computed(() => new Set(steps.value.flatMap((s) => s.blocks)));
const planningBlocks = computed(() => props.reasoning.filter((b) => b.step == null && b.title !== "总结"));
const summaryBlocks = computed(() => props.reasoning.filter((b) => b.step == null && b.title === "总结"));
const looseBlocks = computed(() =>
  items.value.length
    ? props.reasoning.filter((b) => b.step != null && !matchedBlocks.value.has(b))
    : props.reasoning,
);

const done = computed(() => items.value.filter((i) => i.status === "completed").length);
const pct = computed(() => (items.value.length ? Math.round((done.value / items.value.length) * 100) : 0));
const hasContent = computed(() => items.value.length > 0 || props.reasoning.length > 0);

const statusOf = (status: string) =>
  status === "completed" ? "已完成" : status === "in_progress" ? "进行中" : "待执行";

const scrollEl = ref<HTMLElement | null>(null);
const signature = computed(
  () =>
    props.reasoning
      .map((b) => `${b.text.length}:${b.tools?.length ?? 0}:${(b.tools ?? []).map((t) => t.args?.length ?? 0).join(",")}`)
      .join("|") +
    `:${props.streaming}:${items.value.map((i) => i.status).join("")}`,
);

watch(
  signature,
  async () => {
    const el = scrollEl.value;
    if (!el) return;
    const follow = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    await nextTick();
    if (follow) el.scrollTop = el.scrollHeight;
  },
  { flush: "post" },
);

const totalFileCount = computed(() => props.files.length + props.uploads.filter((u) => u.status !== "error").length);
</script>

<template>
  <div
    class="relative flex h-full flex-col"
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

    <!-- Desktop Header (hidden on mobile where drawer provides top header) -->
    <div v-if="!hideHeader" class="shrink-0 px-5 pb-2 pt-3.5 lg:pr-14">
      <div class="flex h-10 items-center justify-between">
        <h3 class="text-[16px] font-semibold text-fg">任务面板</h3>
      </div>
    </div>

    <!-- Split-pane container: Top = Steps, Draggable Handle, Bottom = Files -->
    <div ref="splitContainerRef" class="flex min-h-0 flex-1 flex-col">
      <!-- Top Pane: Steps -->
      <section
        aria-label="步骤"
        class="flex min-h-0 flex-col overflow-hidden"
        :style="{ flexBasis: `${stepsRatio}%`, flexGrow: 0, flexShrink: 0 }"
      >
        <div class="flex shrink-0 items-center justify-between px-4 pb-1.5 pt-2">
          <div class="flex items-center gap-1.5">
            <span class="text-[13px] font-semibold text-fg">步骤</span>
            <span v-if="items.length" class="text-[11.5px] tabular-nums text-fg-faint">{{ done }}/{{ items.length }}</span>
          </div>
          <span v-if="runningTool && streaming" class="max-w-[170px] truncate text-[11.5px] text-fg-muted">
            调用 {{ runningTool }}
          </span>
        </div>

        <div ref="scrollEl" v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto pl-4 pr-1.5 pb-3 pt-1">
          <section v-if="items.length && planningBlocks.length" class="mb-4">
            <h4 class="mb-2 text-[13.5px] font-medium text-fg-muted">规划</h4>
            <div class="space-y-3">
              <div v-for="(block, bi) in planningBlocks" :key="bi">
                <ReasoningEntry :block="block" />
              </div>
            </div>
          </section>

          <section v-if="steps.length" class="mb-4">
            <div class="mb-2 flex items-center justify-between">
              <h4 class="text-[13.5px] font-medium text-fg-muted">执行步骤</h4>
              <span class="text-[12.5px] tabular-nums text-fg-faint">{{ done }} / {{ items.length }}</span>
            </div>
            <div class="mb-3 h-1 overflow-hidden rounded-full bg-surface">
              <div class="h-full rounded-full bg-accent transition-all duration-500" :style="{ width: pct + '%' }" />
            </div>
            <div class="space-y-2">
              <details
                v-for="step in steps"
                :key="stepKey(step)"
                :open="stepOpen(step) && step.blocks.length > 0"
                class="disclosure-card overflow-hidden rounded-xl bg-canvas/75"
              >
                <summary
                  class="focus-ring flex w-full items-start gap-2 px-3 py-2.5 text-left"
                  :class="step.blocks.length ? 'cursor-pointer' : 'cursor-default'"
                  @click.prevent="toggleStep(step)"
                >
                  <span class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                    <span v-if="step.item.status === 'in_progress'" class="text-accent"><Spinner :size="14" /></span>
                    <span
                      v-else-if="step.item.status === 'completed'"
                      class="flex h-4 w-4 items-center justify-center rounded-full bg-success-weak text-success"
                    >
                      <svg class="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    </span>
                    <span v-else class="h-3 w-3 rounded-full border-[1.5px] border-line-strong" />
                  </span>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-1.5">
                      <span class="shrink-0 text-[11.5px] font-medium tabular-nums text-fg-faint">步骤 {{ step.index }}</span>
                      <span
                        class="truncate text-[14px] leading-snug"
                        :class="
                          step.item.status === 'completed'
                            ? 'text-fg-faint'
                            : step.item.status === 'in_progress'
                              ? 'font-medium text-fg'
                              : 'text-fg-muted'
                        "
                      >
                        {{ step.item.content }}
                      </span>
                    </div>
                    <span class="mt-0.5 flex items-center gap-1 text-[12px] text-fg-faint">
                      {{ statusOf(step.item.status) }}
                      <template v-if="!stepOpen(step) && stepMeta(step)"> · {{ stepMeta(step) }}</template>
                    </span>
                  </div>
                  <svg
                    v-if="step.blocks.length"
                    class="mt-1 h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform duration-200"
                    :class="stepOpen(step) ? 'rotate-90' : ''"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
                  </svg>
                </summary>

                <div v-if="step.blocks.length" class="space-y-2 px-3 pb-2.5 pt-0.5">
                  <ReasoningEntry v-for="(block, bi) in step.blocks" :key="bi" :block="block" />
                </div>
              </details>
            </div>
          </section>

          <section v-if="items.length && summaryBlocks.length" class="mb-4">
            <h4 class="mb-2 text-[13.5px] font-medium text-fg-muted">总结</h4>
            <div class="space-y-2">
              <ReasoningEntry v-for="(block, bi) in summaryBlocks" :key="bi" :block="block" />
            </div>
          </section>

          <section v-if="looseBlocks.length" class="mb-4">
            <h4 class="mb-2 text-[13.5px] font-medium text-fg-muted">
              {{ items.length ? "其他记录" : "思考与执行" }}
            </h4>
            <div class="space-y-3">
              <div v-for="(block, bi) in looseBlocks" :key="bi">
                <ReasoningEntry :block="block" />
              </div>
            </div>
          </section>

          <div v-if="runningTool && streaming" class="mt-1 rounded-lg bg-surface px-3 py-2 text-[12.5px] text-fg-muted">
            正在调用 <span class="font-medium text-fg">{{ runningTool }}</span>
          </div>

          <div v-if="!hasContent && !currentStep" class="flex min-h-full items-center justify-center px-4 text-center">
            <p class="text-[13px] leading-relaxed text-fg-faint">
              暂无运行详情。<br />助理处理多步骤任务或读取文件时，这里会按步骤显示思考与工具调用。
            </p>
          </div>
        </div>
      </section>

      <!-- Draggable Split Handle -->
      <div
        role="separator"
        tabindex="0"
        aria-orientation="horizontal"
        aria-label="调整步骤与文件区域高度比例"
        aria-valuemin="20"
        aria-valuemax="80"
        :aria-valuenow="Math.round(stepsRatio)"
        title="上下拖拽调整区域高度"
        class="focus-ring group relative flex h-4 shrink-0 cursor-row-resize touch-none select-none items-center justify-center bg-sidebar transition-colors hover:bg-hover/60"
        :class="draggingSplit ? 'bg-hover/80' : ''"
        @pointerdown="onSplitPointerDown"
        @pointermove="onSplitPointerMove"
        @pointerup="onSplitPointerUp"
        @pointercancel="onSplitPointerUp"
        @keydown="onSplitKeydown"
      >
        <span
          class="h-1 w-9 rounded-full transition-colors"
          :class="draggingSplit ? 'bg-fg-muted' : 'bg-line-strong group-hover:bg-fg-faint'"
          aria-hidden="true"
        />
      </div>

      <!-- Bottom Pane: Files -->
      <section aria-label="文件" class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div class="flex shrink-0 items-center justify-between gap-2 px-4 pb-2 pt-2.5">
          <div class="flex items-center gap-1.5">
            <span class="text-[13px] font-semibold text-fg">文件</span>
            <span class="rounded-full bg-surface px-1.5 py-0.5 text-[11px] tabular-nums text-fg-muted">
              {{ totalFileCount }} / {{ MAX_FILES_PER_CONVERSATION }}
            </span>
          </div>
          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-lg bg-canvas px-2.5 py-1 text-[12px] font-medium text-fg transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="uploadDisabled"
            @click="openFilePicker"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
              <path stroke-linecap="round" d="M12 5v14M5 12h14" />
            </svg>
            <span>上传文件</span>
          </button>
        </div>

        <div v-scrollbar class="custom-scrollbar flex min-h-0 flex-1 flex-col overflow-y-auto pl-4 pr-2.5 pb-4 pt-1">
          <!-- Active upload queue -->
          <div v-if="uploads.length" class="mb-3 space-y-2">
            <div
              v-for="u in uploads"
              :key="u.localId"
              class="rounded-xl p-2.5 text-[12.5px]"
              :class="u.status === 'error' ? 'bg-danger-weak text-danger' : 'bg-canvas/85 text-fg'"
            >
              <div class="flex items-center gap-2">
                <span class="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10.5px] font-medium text-fg-muted">
                  {{ categoryLabel(u.category, u.ext) }}
                </span>
                <span class="min-w-0 flex-1 truncate font-medium" :title="u.filename">{{ u.filename }}</span>
                <span class="shrink-0 tabular-nums text-[11.5px] text-fg-faint">
                  {{ u.status === "signing" ? "签名中" : u.status === "uploading" ? `${u.progress}%` : u.status === "completing" ? "校验中" : "失败" }}
                </span>
                <button
                  type="button"
                  class="focus-ring flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-fg-faint transition-colors hover:bg-hover hover:text-fg"
                  :aria-label="u.status === 'error' ? '关闭错误项' : '取消上传'"
                  @click="u.status === 'error' ? emit('dismiss-upload', u.localId) : emit('cancel-upload', u.localId)"
                >
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </div>
              <progress
                v-if="u.status !== 'error'"
                class="upload-progress mt-2 h-1 w-full"
                :value="u.status === 'uploading' ? u.progress : undefined"
                max="100"
                :aria-label="`${u.filename} 上传进度`"
              />
              <p v-if="u.status === 'error' && u.error" class="mt-1 text-[11.5px]">{{ u.error }}</p>
            </div>
          </div>

          <!-- Ready workspace files -->
          <div v-if="filesLoading && !files.length" class="flex flex-1 items-center justify-center py-6 text-[13px] text-fg-faint">
            正在加载工作区文件…
          </div>

          <div v-else-if="files.length" class="space-y-2">
            <div
              v-for="f in files"
              :key="f.id"
              class="group flex items-center gap-2.5 rounded-xl bg-canvas/80 px-3 py-2.5 transition-colors hover:bg-canvas"
            >
              <span class="shrink-0 rounded-md bg-surface px-1.5 py-0.5 text-[11px] font-medium text-fg-muted">
                {{ categoryLabel(f.category, f.ext) }}
              </span>
              <div class="min-w-0 flex-1">
                <p class="truncate text-[13.5px] font-medium text-fg" :title="f.filename">{{ f.filename }}</p>
                <p class="text-[11.5px] tabular-nums text-fg-faint">{{ formatFileSize(f.size_bytes) }}</p>
              </div>
              <div class="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
                  aria-label="下载文件"
                  title="通过临时签名直链下载"
                  :disabled="downloadingId === f.id"
                  @click="onDownloadClick(f)"
                >
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
                  </svg>
                </button>
                <button
                  type="button"
                  class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-danger-weak hover:text-danger"
                  aria-label="删除文件"
                  title="从当前对话工作区移除"
                  :disabled="deletingId === f.id"
                  @click="onDeleteClick(f.id)"
                >
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M8 6V4h8v2m-9 0l1 14h8l1-14" />
                  </svg>
                </button>
              </div>
            </div>

            <p class="pt-1 text-[12px] leading-relaxed text-fg-faint">
              当前对话内，AI 可随时读取工作区内的全部文件；支持将文件直接拖拽至此面板。
            </p>
          </div>

          <div
            v-else-if="!uploads.length"
            class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-line px-4 py-6 text-center"
          >
            <svg class="mb-2 h-6 w-6 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"
              />
              <path stroke-linecap="round" stroke-linejoin="round" d="M14 2v6h6M12 18v-6m0 0l-2.5 2.5M12 12l2.5 2.5" />
            </svg>
            <p class="text-[13px] font-medium text-fg-muted">工作区暂无文件</p>
            <p class="mt-1 text-[11.5px] leading-relaxed text-fg-faint">
              支持拖拽文件至此或点击上方「上传文件」
            </p>
            <p class="mt-1.5 text-[11px] leading-relaxed text-fg-faint/85">
              {{ SUPPORTED_TYPES_SUMMARY }}
            </p>
          </div>
        </div>
      </section>
    </div>

    <!-- Full Task Panel Drag Overlay -->
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
        class="pointer-events-none absolute inset-2 z-20 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-5 text-center backdrop-blur-[2px]"
        :class="
          dragValid
            ? 'border-accent bg-sidebar/94 text-fg'
            : 'border-danger bg-danger-weak/94 text-danger'
        "
      >
        <p class="text-[14px] font-medium">
          {{ dragValid ? "松开以添加到当前对话文件区" : "不支持的文件类型" }}
        </p>
        <p class="mt-1 text-[12px] leading-relaxed opacity-85">
          {{ dragValid ? SUPPORTED_TYPES_SUMMARY : dragReason }}
        </p>
      </div>
    </Transition>
  </div>
</template>
