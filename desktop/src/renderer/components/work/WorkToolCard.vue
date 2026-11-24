<script setup lang="ts">
import { computed, ref } from "vue";
import type { WorkTimelineItem } from "@shared/work-types";
import { stripAnsi } from "../../lib/unifiedDiff";

const props = defineProps<{
  item: WorkTimelineItem;
  workspacePath?: string | null;
}>();

const emit = defineEmits<{
  previewFile: [string];
  openDiffTab: [];
}>();

const copiedCmd = ref(false);
const subLoading = ref(false);
const subExpanded = ref(false);
const subItems = ref<WorkTimelineItem[]>([]);

const toolName = computed(() => props.item.tool ?? "");

const toolLabel = computed(() => {
  const map: Record<string, string> = {
    read: "读取文件",
    read_file: "读取文件",
    write: "写入文件",
    write_file: "写入文件",
    edit: "编辑文件",
    multiedit: "批量编辑",
    apply_patch: "应用补丁",
    patch: "修改补丁",
    glob: "文件匹配",
    grep: "全文搜索",
    list: "目录浏览",
    bash: "终端命令",
    terminal: "终端命令",
    execute_code: "代码执行",
    webfetch: "抓取网页",
    websearch: "网页检索",
    todowrite: "任务计划",
    task: "子代理任务",
    skill: "读取技能",
  };
  return map[toolName.value] || toolName.value || "工具调用";
});

const parsedArgs = computed<Record<string, unknown> | null>(() => {
  const raw = props.item.args;
  if (!raw) return null;
  if (typeof raw === "object" && !Array.isArray(raw)) return raw as Record<string, unknown>;
  if (typeof raw === "string") {
    try {
      const p = JSON.parse(raw);
      return p && typeof p === "object" && !Array.isArray(p) ? (p as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }
  return null;
});

const filePath = computed<string | null>(() => {
  const args = parsedArgs.value;
  if (!args) return null;
  const p = args.filePath ?? args.path ?? args.file_path ?? args.target_file;
  return typeof p === "string" && p.trim() ? p.trim() : null;
});

const bashCommand = computed<string | null>(() => {
  if (!["bash", "terminal", "execute_code"].includes(toolName.value)) return null;
  const args = parsedArgs.value;
  const cmd = args?.command ?? args?.cmd ?? args?.script;
  return typeof cmd === "string" && cmd.trim() ? cmd.trim() : null;
});

const isEditTool = computed(() => ["edit", "write", "write_file", "patch", "multiedit", "apply_patch"].includes(toolName.value));

const cleanResultText = computed(() => {
  const raw = props.item.error ?? props.item.result;
  if (raw === null || raw === undefined) return "";
  const str = typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
  return stripAnsi(str);
});

const summaryLine = computed(() => {
  if (bashCommand.value) return bashCommand.value.split(/\r?\n/)[0].slice(0, 90);
  if (filePath.value) return filePath.value;
  if (props.item.title?.trim()) return props.item.title.trim();
  if (parsedArgs.value?.pattern) return String(parsedArgs.value.pattern);
  if (parsedArgs.value?.url) return String(parsedArgs.value.url);
  if (parsedArgs.value?.query) return String(parsedArgs.value.query);
  if (props.item.args) {
    const s = typeof props.item.args === "string" ? props.item.args : JSON.stringify(props.item.args);
    return s.replace(/\s+/g, " ").slice(0, 90);
  }
  return "";
});

const dotColor = computed(() => {
  if (props.item.status === "running") return "var(--warning)";
  if (props.item.status === "failed") return "var(--danger)";
  return "var(--success)";
});

async function copyCommand() {
  if (!bashCommand.value) return;
  try {
    await navigator.clipboard.writeText(bashCommand.value);
    copiedCmd.value = true;
    setTimeout(() => {
      copiedCmd.value = false;
    }, 1500);
  } catch {
    /* ignore */
  }
}

async function toggleSubsessionTrace() {
  if (!props.item.child_session_id) return;
  subExpanded.value = !subExpanded.value;
  if (subExpanded.value && !subItems.value.length) {
    subLoading.value = true;
    try {
      subItems.value =
        (await window.whitzDesktop?.work.subsessionMessages(props.item.child_session_id, props.workspacePath)) ?? [];
    } catch {
      subItems.value = [];
    } finally {
      subLoading.value = false;
    }
  }
}
</script>

<template>
  <!-- Patch Milestone Pill -->
  <div
    v-if="item.kind === 'patch'"
    class="flex items-center justify-between gap-2 rounded-xl bg-canvas/75 px-3 py-2 text-[11.5px] text-fg-muted"
  >
    <div class="min-w-0 flex-1">
      <span class="font-medium text-fg">{{ item.title || "文件快照变更" }}</span>
      <p v-if="item.files?.length" class="mt-0.5 truncate font-mono text-[10.5px] text-fg-faint">
        {{ item.files.join(", ") }}
      </p>
    </div>
    <button
      type="button"
      class="shrink-0 rounded-lg bg-surface px-2 py-0.5 text-[11px] text-fg-muted hover:text-fg"
      @click="emit('openDiffTab')"
    >
      查看变更
    </button>
  </div>

  <!-- Compaction / Retry Milestone -->
  <div
    v-else-if="item.kind === 'compaction' || item.kind === 'retry'"
    class="flex items-center gap-2 rounded-xl px-3 py-1.5 text-[11.5px]"
    :class="item.kind === 'retry' ? 'bg-warning-weak/70 text-warning' : 'bg-canvas/65 text-fg-faint'"
  >
    <span class="h-1.5 w-1.5 shrink-0 rounded-full" :style="{ background: item.kind === 'retry' ? 'var(--warning)' : 'var(--accent)' }" />
    <span class="font-medium">{{ item.title }}</span>
    <span v-if="item.error" class="min-w-0 flex-1 truncate opacity-80">{{ item.error }}</span>
  </div>

  <!-- Rich Tool / Subagent Disclosure Card -->
  <details
    v-else
    class="disclosure-card rounded-2xl bg-canvas/85 text-[12px]"
    :open="item.status === 'running' || item.status === 'failed'"
  >
    <summary class="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2 select-none">
      <span
        class="h-1.5 w-1.5 shrink-0 rounded-full"
        :class="{ 'animate-pulse': item.status === 'running' }"
        :style="{ background: dotColor }"
      />
      <span class="shrink-0 font-medium text-fg">{{ toolLabel }}</span>
      <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-faint" :title="summaryLine">
        {{ summaryLine }}
      </span>
      <button
        v-if="filePath"
        type="button"
        class="shrink-0 rounded-lg bg-surface px-2 py-0.5 text-[10.5px] text-fg-muted transition-colors hover:text-fg"
        @click.stop.prevent="emit('previewFile', filePath)"
      >
        预览
      </button>
      <button
        v-if="isEditTool"
        type="button"
        class="shrink-0 rounded-lg bg-surface px-2 py-0.5 text-[10.5px] text-fg-muted transition-colors hover:text-fg"
        @click.stop.prevent="emit('openDiffTab')"
      >
        Diff
      </button>
      <span v-if="typeof item.duration === 'number'" class="shrink-0 text-[10.5px] tabular-nums text-fg-faint">
        {{ item.duration.toFixed(1) }}s
      </span>
    </summary>

    <div class="space-y-2 px-3.5 pb-3 pt-1">
      <!-- Specialized Bash Header -->
      <div v-if="bashCommand" class="rounded-xl bg-code px-3 py-2 font-mono text-[11px] text-[#e6e5e0]">
        <div class="flex items-start justify-between gap-2">
          <pre class="m-0 min-w-0 flex-1 whitespace-pre-wrap break-all"><span class="select-none text-[#e0a858]">$ </span>{{ bashCommand }}</pre>
          <button
            type="button"
            class="shrink-0 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/80 hover:bg-white/20"
            @click="copyCommand"
          >
            {{ copiedCmd ? "已复制" : "复制" }}
          </button>
        </div>
      </div>

      <!-- Specialized Edit Old/New Preview -->
      <div
        v-else-if="isEditTool && parsedArgs && (typeof parsedArgs.oldString === 'string' || typeof parsedArgs.newString === 'string')"
        class="max-h-48 overflow-auto rounded-xl bg-code p-2 font-mono text-[11px] leading-relaxed"
      >
        <pre v-if="typeof parsedArgs.oldString === 'string'" class="m-0 whitespace-pre-wrap break-words bg-[#3d1c1c]/60 px-2 py-1 text-[#fca5a5]">- {{ parsedArgs.oldString.slice(0, 600) }}</pre>
        <pre v-if="typeof parsedArgs.newString === 'string'" class="m-0 mt-1 whitespace-pre-wrap break-words bg-[#193524]/60 px-2 py-1 text-[#a7f3c0]">+ {{ parsedArgs.newString.slice(0, 600) }}</pre>
      </div>

      <!-- Generic Structured Args -->
      <pre
        v-else-if="item.args"
        class="max-h-36 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code px-3 py-2 font-mono text-[11px] leading-relaxed text-[#c6c5be]"
      >{{ typeof item.args === "string" ? item.args : JSON.stringify(item.args, null, 2) }}</pre>

      <!-- Result / Output -->
      <pre
        v-if="cleanResultText"
        class="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code px-3 py-2 font-mono text-[11px] leading-relaxed"
        :class="item.status === 'failed' ? 'text-[#f3a6a0]' : 'text-[#d6d5ce]'"
      >{{ cleanResultText }}</pre>

      <!-- Subagent Child Session Drill-down -->
      <div v-if="item.child_session_id" class="pt-0.5">
        <button
          type="button"
          class="rounded-lg bg-surface px-2.5 py-1 text-[11px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="toggleSubsessionTrace"
        >
          {{ subExpanded ? "收起子代理执行轨迹" : "展开子代理执行轨迹" }}
        </button>
        <div v-if="subExpanded" class="mt-2 space-y-1.5 border-l-2 border-line pl-2.5">
          <p v-if="subLoading" class="text-[11px] text-fg-faint">正在加载子会话步骤…</p>
          <p v-else-if="!subItems.length" class="text-[11px] text-fg-faint">暂无子会话记录</p>
          <div
            v-for="child in subItems"
            :key="child.id"
            class="rounded-lg bg-surface/65 px-2.5 py-1.5 text-[11px] text-fg-muted"
          >
            <span class="font-medium text-fg">{{ child.tool || child.title || child.kind }}</span>
            <p v-if="child.text" class="mt-0.5 line-clamp-3 whitespace-pre-wrap text-[11px] text-fg-faint">{{ child.text }}</p>
          </div>
        </div>
      </div>
    </div>
  </details>
</template>
