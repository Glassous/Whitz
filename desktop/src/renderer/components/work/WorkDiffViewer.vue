<script setup lang="ts">
import { computed, ref } from "vue";
import { parseUnifiedDiff } from "../../lib/unifiedDiff";

const props = defineProps<{
  filePath: string;
  patch: string;
  additions?: number;
  deletions?: number;
  canRevert?: boolean;
  canExpand?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  openFile: [string];
  openExplorer: [string];
  insertPath: [string];
  revertFile: [string];
  expand: [];
}>();

const mode = ref<"unified" | "split">("unified");
const copied = ref(false);
const confirmingRevert = ref(false);

const parsed = computed(() => parseUnifiedDiff(props.patch));
const statsAdd = computed(() => props.additions ?? parsed.value.additions);
const statsDel = computed(() => props.deletions ?? parsed.value.deletions);

async function copyPath() {
  try {
    await navigator.clipboard.writeText(props.filePath);
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1500);
  } catch {
    /* ignore */
  }
}

function handleRevertClick() {
  if (!confirmingRevert.value) {
    confirmingRevert.value = true;
    setTimeout(() => {
      confirmingRevert.value = false;
    }, 3500);
    return;
  }
  confirmingRevert.value = false;
  emit("revertFile", props.filePath);
}

function lineBg(kind: string): string {
  if (kind === "add") return "bg-[#193524]/75 text-[#a7f3c0]";
  if (kind === "del") return "bg-[#3d1c1c]/75 text-[#fca5a5]";
  if (kind === "hunk") return "bg-[#1e293b]/80 text-[#93c5fd]";
  if (kind === "meta") return "text-[#9ca3af]";
  if (kind === "empty") return "bg-white/[0.02] text-transparent";
  return "text-[#d6d5ce]";
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-canvas">
    <!-- Header -->
    <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <p class="truncate font-mono text-[12px] font-medium text-fg" :title="filePath">{{ filePath }}</p>
          <span v-if="statsAdd > 0" class="shrink-0 font-mono text-[11px] text-success">+{{ statsAdd }}</span>
          <span v-if="statsDel > 0" class="shrink-0 font-mono text-[11px] text-danger">-{{ statsDel }}</span>
        </div>
      </div>

      <div class="flex shrink-0 items-center gap-1">
        <div class="mr-1 flex items-center rounded-lg bg-surface p-0.5 text-[11px]">
          <button
            type="button"
            class="rounded-md px-2 py-0.5 transition-colors"
            :class="mode === 'unified' ? 'bg-canvas font-medium text-fg shadow-xs' : 'text-fg-faint hover:text-fg'"
            @click="mode = 'unified'"
          >
            单栏
          </button>
          <button
            type="button"
            class="rounded-md px-2 py-0.5 transition-colors"
            :class="mode === 'split' ? 'bg-canvas font-medium text-fg shadow-xs' : 'text-fg-faint hover:text-fg'"
            @click="mode = 'split'"
          >
            双栏
          </button>
        </div>

        <button
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          title="打开原文件预览"
          @click="emit('openFile', filePath)"
        >
          文件
        </button>
        <button
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          title="引用路径到输入框 (@)"
          @click="emit('insertPath', filePath)"
        >
          @
        </button>
        <button
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          @click="copyPath"
        >
          {{ copied ? "已复制" : "复制" }}
        </button>
        <button
          v-if="canRevert"
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] transition-colors"
          :class="confirmingRevert ? 'bg-danger text-white' : 'text-danger hover:bg-danger-weak'"
          title="丢弃此文件未提交修改"
          @click="handleRevertClick"
        >
          {{ confirmingRevert ? "确认丢弃" : "回滚" }}
        </button>
        <button
          v-if="canExpand"
          type="button"
          class="rounded-lg p-1 text-fg-faint hover:bg-hover hover:text-fg"
          title="全屏放大评审"
          aria-label="全屏放大评审"
          @click="emit('expand')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
          </svg>
        </button>
        <button
          type="button"
          class="rounded-lg p-1 text-fg-faint hover:bg-hover hover:text-fg"
          aria-label="关闭差异预览"
          @click="emit('close')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Diff Body -->
    <div class="min-h-0 flex-1 overflow-auto custom-scrollbar bg-code font-mono text-[11.5px] leading-[1.55]">
      <div v-if="!parsed.lines.length" class="p-6 text-center text-[12px] text-[#9ca3af]">暂无差异内容</div>

      <!-- Unified View -->
      <div v-else-if="mode === 'unified'" class="min-w-fit py-1.5">
        <div
          v-for="(line, idx) in parsed.lines"
          :key="idx"
          class="flex items-stretch px-2"
          :class="lineBg(line.kind)"
        >
          <span class="w-9 shrink-0 select-none pr-2 text-right text-[10.5px] opacity-45 tabular-nums">
            {{ line.oldLine ?? "" }}
          </span>
          <span class="w-9 shrink-0 select-none pr-2 text-right text-[10.5px] opacity-45 tabular-nums">
            {{ line.newLine ?? "" }}
          </span>
          <span class="w-4 shrink-0 select-none text-center opacity-75">
            {{ line.kind === "add" ? "+" : line.kind === "del" ? "-" : "" }}
          </span>
          <span class="min-w-0 flex-1 whitespace-pre">{{ line.text || " " }}</span>
        </div>
      </div>

      <!-- Split Side-by-Side View -->
      <div v-else class="min-w-[640px] py-1.5">
        <template v-for="(row, idx) in parsed.splitRows" :key="idx">
          <div v-if="row.kind === 'hunk'" class="bg-[#1e293b]/80 px-3 py-0.5 text-[11px] text-[#93c5fd]">
            {{ row.hunkText }}
          </div>
          <div v-else class="grid grid-cols-2 divide-x divide-white/10">
            <div class="flex min-w-0 items-stretch px-2" :class="lineBg(row.left.kind)">
              <span class="w-9 shrink-0 select-none pr-2 text-right text-[10.5px] opacity-45 tabular-nums">
                {{ row.left.line ?? "" }}
              </span>
              <span class="w-3.5 shrink-0 select-none opacity-75">{{ row.left.kind === "del" ? "-" : "" }}</span>
              <span class="min-w-0 flex-1 whitespace-pre-wrap break-all">{{ row.left.text || " " }}</span>
            </div>
            <div class="flex min-w-0 items-stretch px-2" :class="lineBg(row.right.kind)">
              <span class="w-9 shrink-0 select-none pr-2 text-right text-[10.5px] opacity-45 tabular-nums">
                {{ row.right.line ?? "" }}
              </span>
              <span class="w-3.5 shrink-0 select-none opacity-75">{{ row.right.kind === "add" ? "+" : "" }}</span>
              <span class="min-w-0 flex-1 whitespace-pre-wrap break-all">{{ row.right.text || " " }}</span>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
