<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";
import type { WorkTimelineItem } from "@shared/work-types";
import { buildFallbackPatch } from "../../lib/unifiedDiff";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore, type WorkInspectorTab } from "../../stores/work";
import { useSmartStreamScroll } from "@web/composables/useSmartStreamScroll";
import BaseButton from "@web/components/ui/BaseButton.vue";
import WorkspaceTreeNode from "./WorkspaceTreeNode.vue";
import WorkFilePreview from "./WorkFilePreview.vue";
import WorkDiffViewer from "./WorkDiffViewer.vue";
import WorkToolCard from "./WorkToolCard.vue";

const emit = defineEmits<{
  insertPath: [string];
  close: [];
}>();

const router = useRouter();
const runtime = useRuntimeStore();
const work = useWorkStore();

const diffScope = ref<"session" | "git">("session");
const selectedSessionDiffFile = ref<string | null>(null);
const stepsScroller = ref<HTMLElement | null>(null);
const stepsScroll = useSmartStreamScroll(stepsScroller);

const tabs: Array<{ key: WorkInspectorTab; label: string }> = [
  { key: "steps", label: "步骤" },
  { key: "files", label: "文件" },
  { key: "git", label: "变更" },
  { key: "runtime", label: "运行" },
];

const assistantTurns = computed(() => work.messages.filter((m) => m.role === "assistant"));
const activeTurnIndex = computed(() => {
  if (!assistantTurns.value.length) return -1;
  if (work.selectedTurnId) {
    const idx = assistantTurns.value.findIndex((m) => m.id === work.selectedTurnId);
    if (idx >= 0) return idx;
  }
  return assistantTurns.value.length - 1;
});
const activeTurn = computed(() =>
  activeTurnIndex.value >= 0 ? assistantTurns.value[activeTurnIndex.value] : null,
);
const selectedTimeline = computed<WorkTimelineItem[]>(() =>
  activeTurn.value ? work.getTurnTimeline(activeTurn.value, work.messages) : [],
);

const rootEntries = computed(() => work.childrenByDir[""] ?? []);
const planItems = computed(() => {
  const turnPlan = activeTurn.value?.tool_payload?.plan as { items?: Array<Record<string, unknown>> } | undefined;
  const items = turnPlan?.items ?? ((work.plan?.items ?? []) as Array<Record<string, unknown>>);
  return Array.isArray(items) ? items : [];
});

const activeBranch = computed(() => work.vcsBranch || work.gitStatus.branch || null);
const totalChangesBadge = computed(() => work.sessionDiffs.length || work.gitStatus.changes.length);

function previewStepFile(relPath: string) {
  void work.openFilePreview(relPath);
  work.inspectorTab = "files";
}

function switchTurn(delta: number) {
  const next = activeTurnIndex.value + delta;
  if (next < 0 || next >= assistantTurns.value.length) return;
  work.selectedTurnId = assistantTurns.value[next].id;
}

watch(
  () => {
    const last = selectedTimeline.value[selectedTimeline.value.length - 1];
    return [
      activeTurn.value?.id ?? "",
      selectedTimeline.value.length,
      last?.text?.length ?? 0,
      last?.status ?? "",
      work.inspectorTab,
    ] as const;
  },
  async ([turnId, , , , tab], prev) => {
    if (tab !== "steps") return;
    if (prev && turnId !== prev[0]) stepsScroll.autoFollow.value = true;
    if (!stepsScroll.autoFollow.value) return;
    await nextTick();
    stepsScroll.followBottomSmooth();
  },
  { flush: "post" },
);

const activeSessionDiff = computed(() => {
  if (!selectedSessionDiffFile.value) return null;
  return work.sessionDiffs.find((d) => d.file === selectedSessionDiffFile.value) ?? null;
});

const stateLabel = computed(() => {
  const state = runtime.status?.state;
  return (
    {
      ready: "运行中",
      starting: "启动中",
      stopped: "已停止",
      error: "异常",
      disabled: "已禁用",
      idle: "待机",
    } as Record<string, string>
  )[state ?? "idle"] ?? "未知";
});

const stateColor = computed(() => {
  if (runtime.ready) return "var(--success)";
  if (runtime.status?.state === "error") return "var(--danger)";
  if (runtime.status?.state === "starting") return "var(--warning)";
  return "var(--fg-faint)";
});

function gitBadgeColor(status: string): string {
  if (status.includes("?") || status === "added") return "text-success";
  if (status.includes("D") || status === "deleted") return "text-danger";
  return "text-warning";
}

function openSessionDiffItem(file: string) {
  selectedSessionDiffFile.value = file;
  const item = work.sessionDiffs.find((d) => d.file === file);
  if (!item) return;
  const patch = item.patch?.trim()
    ? item.patch
    : buildFallbackPatch(item.file, item.before ?? "", item.after ?? "");
  work.previewDiff = { path: item.file, diff: patch };
}

async function handleRevertFile(relPath: string) {
  try {
    await work.revertFile(relPath);
  } catch (err) {
    work.error = err instanceof Error ? err.message : "回滚文件失败";
  }
}

watch(
  () => work.inspectorTab,
  (tab) => {
    const dir = work.activeWorkspace?.path ?? null;
    if (tab === "runtime") {
      void runtime.loadMcpServers(dir);
      void runtime.loadLspStatus(dir);
      void runtime.loadFormatterStatus(dir);
    } else if (tab === "git") {
      void work.refreshSessionDiff();
      if (!work.sessionDiffs.length && work.gitStatus.changes.length) {
        diffScope.value = "git";
      }
    }
  },
);
</script>

<template>
  <aside class="flex h-full w-full flex-col bg-sidebar">
    <!-- Top Tabs Header -->
    <div class="flex h-13 shrink-0 items-center justify-between gap-2 px-3 pr-14 pt-1">
      <div class="flex min-w-0 items-center gap-0.5 rounded-xl bg-surface/65 p-0.5">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          type="button"
          class="focus-ring inline-flex shrink-0 items-center whitespace-nowrap rounded-lg px-2 py-1 text-[12px] font-medium transition-colors"
          :class="work.inspectorTab === tab.key ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
          @click="work.inspectorTab = tab.key"
        >
          <span>{{ tab.label }}</span>
          <span
            v-if="tab.key === 'steps' && selectedTimeline.length"
            class="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-surface px-1 text-[10px] leading-none tabular-nums text-fg"
          >
            {{ selectedTimeline.length }}
          </span>
          <span
            v-else-if="tab.key === 'git' && totalChangesBadge > 0"
            class="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-surface px-1 text-[10px] leading-none tabular-nums text-fg"
          >
            {{ totalChangesBadge }}
          </span>
        </button>
      </div>

      <button
        v-if="work.activeWorkspace && (work.inspectorTab === 'files' || work.inspectorTab === 'git')"
        type="button"
        class="focus-ring flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
        title="刷新工作区"
        @click="work.refreshWorkspace()"
      >
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6" />
        </svg>
      </button>
    </div>

    <!-- Tab 1: Chronological Steps & Deep Thinking + Plan + Subagents -->
    <div
      v-if="work.inspectorTab === 'steps'"
      ref="stepsScroller"
      class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto custom-scrollbar p-3"
    >
      <div
        v-if="assistantTurns.length > 1"
        class="flex items-center justify-between gap-2 rounded-xl bg-canvas/75 px-3 py-1.5 text-[11.5px] text-fg-muted"
      >
        <span>第 {{ activeTurnIndex + 1 }} / {{ assistantTurns.length }} 轮</span>
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="rounded-md px-1.5 py-0.5 transition-colors hover:bg-hover hover:text-fg disabled:opacity-35"
            :disabled="activeTurnIndex <= 0"
            @click="switchTurn(-1)"
          >
            上一轮
          </button>
          <button
            type="button"
            class="rounded-md px-1.5 py-0.5 transition-colors hover:bg-hover hover:text-fg disabled:opacity-35"
            :disabled="activeTurnIndex >= assistantTurns.length - 1"
            @click="switchTurn(1)"
          >
            下一轮
          </button>
        </div>
      </div>

      <!-- Task Plan / Todos -->
      <section v-if="planItems.length" class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">任务计划</span>
          <span class="text-[11px] tabular-nums text-fg-faint">{{ planItems.length }} 步</span>
        </div>
        <ol class="mt-2.5 space-y-2">
          <li v-for="(item, index) in planItems" :key="String(item.id ?? index)" class="flex items-start gap-2">
            <span
              class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
              :style="{
                background:
                  item.status === 'completed'
                    ? 'var(--success)'
                    : item.status === 'in_progress'
                      ? 'var(--work-accent)'
                      : 'var(--line-strong)',
              }"
            />
            <span
              class="text-[12px] leading-relaxed"
              :class="item.status === 'completed' ? 'text-fg-faint line-through' : 'text-fg-muted'"
            >
              {{ String(item.content ?? "") }}
            </span>
          </li>
        </ol>
      </section>

      <!-- Live Subagents -->
      <section v-if="work.subagents.length" class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">子代理委派</span>
          <span class="text-[11px] tabular-nums text-fg-faint">{{ work.subagents.length }}</span>
        </div>
        <div class="mt-2.5 space-y-2">
          <div v-for="sub in work.subagents" :key="sub.id" class="rounded-xl bg-surface/65 px-3 py-2 text-[12px]">
            <div class="flex items-center justify-between gap-2">
              <span class="truncate font-medium text-fg">{{ sub.goal }}</span>
              <span class="shrink-0 text-[10.5px] tabular-nums text-fg-faint">
                <template v-if="sub.toolCount">{{ sub.toolCount }} 工具 · </template>
                {{ sub.status === "running" ? "运行中" : "已完成" }}
              </span>
            </div>
            <p v-if="sub.summary" class="mt-1 text-[11.5px] text-fg-muted">{{ sub.summary }}</p>
          </div>
        </div>
      </section>

      <!-- Chronological Execution Timeline -->
      <div v-if="!selectedTimeline.length && !planItems.length" class="flex flex-1 flex-col items-center justify-center rounded-2xl bg-canvas/55 p-6 text-center">
        <p class="text-[13px] font-medium text-fg">暂无执行步骤</p>
        <p class="mt-1.5 text-[12px] leading-relaxed text-fg-faint">
          深度思考、命令输出、补丁改动与子代理委派会按时间顺序实时显示在这里，主对话区仅保留最终结果。
        </p>
      </div>

      <template v-else>
        <template v-for="item in selectedTimeline" :key="item.id">
          <!-- Deep Thinking Block -->
          <details
            v-if="item.kind === 'thinking'"
            class="disclosure-card rounded-2xl bg-canvas/85 text-[12px]"
            open
          >
            <summary class="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2 select-none">
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                :class="{ 'animate-pulse': item.status === 'running' }"
                :style="{ background: item.status === 'running' ? 'var(--work-accent)' : 'var(--fg-faint)' }"
              />
              <span class="font-medium text-fg">{{ item.title || "深度思考" }}</span>
              <span class="ml-auto text-[11px] text-fg-faint">
                {{ item.status === "running" ? "思考中…" : "已完成" }}
              </span>
            </summary>
            <div class="px-3.5 pb-3 pt-0.5">
              <p class="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-fg-muted">{{ item.text }}</p>
            </div>
          </details>

          <!-- Pre-tool Commentary -->
          <div
            v-else-if="item.kind === 'commentary'"
            class="rounded-2xl bg-canvas/65 px-3.5 py-2.5 text-[12px] leading-relaxed text-fg-muted"
          >
            <p class="whitespace-pre-wrap break-words">{{ item.text }}</p>
          </div>

          <!-- Specialized Tool / Subagent / Patch / Retry / Compaction Card -->
          <WorkToolCard
            v-else
            :item="item"
            :workspace-path="work.activeWorkspace?.path"
            @preview-file="previewStepFile"
            @open-diff-tab="work.inspectorTab = 'git'; work.refreshSessionDiff()"
          />
        </template>
      </template>
    </div>

    <!-- Tab 2: Workspace Files -->
    <div v-else-if="work.inspectorTab === 'files'" class="flex min-h-0 flex-1 flex-col gap-2.5 p-3">
      <div v-if="!work.activeWorkspace" class="flex flex-1 flex-col items-center justify-center rounded-2xl bg-canvas/55 p-6 text-center">
        <p class="text-[13px] font-medium text-fg">尚未选定本地项目</p>
        <p class="mt-1.5 text-[12px] leading-relaxed text-fg-faint">
          在左侧 Projects 添加或选择一个文件夹后，可浏览目录并让 OpenCode 直接读写源码。
        </p>
        <BaseButton size="sm" class="mt-4" @click="work.pickWorkspace()">打开项目文件夹</BaseButton>
      </div>

      <template v-else>
        <div class="flex items-center justify-between gap-2 px-1">
          <span class="truncate text-[12px] font-medium text-fg-muted" :title="work.activeWorkspace.path">
            {{ work.activeWorkspace.name }}
          </span>
          <div class="flex shrink-0 items-center gap-2 text-[11px] text-fg-faint">
            <button type="button" class="hover:text-fg" title="快速定位文件 (Ctrl+P)" @click="work.openCommandPalette('files')">
              搜索
            </button>
            <button type="button" class="hover:text-fg" title="由 OpenCode 自动分析生成项目 AGENTS.md" @click="work.initAgentsMd()">
              /init
            </button>
            <button type="button" class="hover:text-fg" @click="work.openInExplorer()">
              目录
            </button>
          </div>
        </div>

        <div
          class="min-h-0 overflow-y-auto custom-scrollbar rounded-2xl bg-canvas/70 p-1.5"
          :class="work.previewFile ? 'max-h-[42%] shrink-0' : 'flex-1'"
        >
          <div v-if="work.treeLoading && !rootEntries.length" class="p-4 text-center text-[12px] text-fg-faint">
            读取目录中…
          </div>
          <template v-else-if="rootEntries.length">
            <WorkspaceTreeNode
              v-for="entry in rootEntries"
              :key="entry.rel_path"
              :entry="entry"
              @insert-path="emit('insertPath', $event)"
            />
          </template>
          <p v-else class="p-4 text-center text-[12px] text-fg-faint">目录为空</p>
        </div>

        <WorkFilePreview
          v-if="work.previewFile"
          :file="work.previewFile"
          @close="work.previewFile = null"
          @open-explorer="work.openInExplorer($event)"
          @open-editor="work.openInEditor($event)"
          @insert-path="emit('insertPath', $event)"
        />
      </template>
    </div>

    <!-- Tab 3: Session Diff & Git Changes with Unified/Split Viewer -->
    <div v-else-if="work.inspectorTab === 'git'" class="flex min-h-0 flex-1 flex-col gap-2.5 p-3">
      <div class="flex items-center justify-between gap-2 px-1 text-[12px]">
        <div class="flex items-center gap-1 rounded-xl bg-surface/75 p-0.5">
          <button
            type="button"
            class="rounded-lg px-2 py-0.5 text-[11.5px] transition-colors"
            :class="diffScope === 'session' ? 'bg-canvas text-fg font-medium' : 'text-fg-faint hover:text-fg'"
            @click="diffScope = 'session'"
          >
            本任务 ({{ work.sessionDiffs.length }})
          </button>
          <button
            type="button"
            class="rounded-lg px-2 py-0.5 text-[11.5px] transition-colors"
            :class="diffScope === 'git' ? 'bg-canvas text-fg font-medium' : 'text-fg-faint hover:text-fg'"
            @click="diffScope = 'git'"
          >
            仓库 ({{ work.gitStatus.changes.length }})
          </button>
        </div>

        <div class="flex min-w-0 items-center gap-1.5">
          <span v-if="activeBranch" class="truncate font-mono text-[11px] text-fg-faint" :title="`当前分支: ${activeBranch}`">
            ⎇ {{ activeBranch }}
          </span>
          <button
            v-if="work.sessionDiffs.length || work.gitStatus.changes.length"
            type="button"
            class="shrink-0 rounded-md px-1.5 py-0.5 text-[11px] text-fg-faint hover:bg-hover hover:text-fg"
            title="全屏评审变更"
            @click="work.diffModalOpen = true"
          >
            放大
          </button>
        </div>
      </div>

      <!-- Session-level Diff -->
      <template v-if="diffScope === 'session'">
        <div
          class="min-h-0 overflow-y-auto custom-scrollbar rounded-2xl bg-canvas/70 p-1.5"
          :class="work.previewDiff ? 'max-h-[38%] shrink-0' : 'flex-1'"
        >
          <div v-if="!work.sessionDiffs.length" class="p-4 text-center text-[12px] text-fg-faint">
            当前会话尚未产生文件快照改动
          </div>
          <button
            v-for="item in work.sessionDiffs"
            :key="item.file"
            type="button"
            class="flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-hover"
            :class="activeSessionDiff?.file === item.file ? 'bg-active text-fg font-medium' : 'text-fg-muted'"
            @click="openSessionDiffItem(item.file)"
          >
            <span class="min-w-0 flex-1 truncate font-mono text-[11.5px]">{{ item.file }}</span>
            <span class="shrink-0 font-mono text-[11px] tabular-nums" :class="gitBadgeColor(item.status ?? 'modified')">
              <template v-if="item.additions !== undefined || item.deletions !== undefined">
                +{{ item.additions ?? 0 }} / -{{ item.deletions ?? 0 }}
              </template>
              <template v-else>{{ item.status ?? "M" }}</template>
            </span>
          </button>
        </div>
      </template>

      <!-- Repo Git Diff -->
      <template v-else>
        <div v-if="!work.activeWorkspace || !work.gitStatus.is_repo" class="flex flex-1 items-center justify-center rounded-2xl bg-canvas/55 p-6 text-center text-[12px] text-fg-faint">
          当前目录不是 Git 仓库或尚未选定工作区
        </div>
        <div
          v-else
          class="min-h-0 overflow-y-auto custom-scrollbar rounded-2xl bg-canvas/70 p-1.5"
          :class="work.previewDiff ? 'max-h-[38%] shrink-0' : 'flex-1'"
        >
          <div v-if="!work.gitStatus.changes.length" class="p-4 text-center text-[12px] text-fg-faint">
            工作区干净，暂无未提交改动
          </div>
          <button
            v-for="change in work.gitStatus.changes"
            :key="`${change.staged}-${change.path}`"
            type="button"
            class="flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-hover"
            :class="work.previewDiff?.path === change.path ? 'bg-active text-fg font-medium' : 'text-fg-muted'"
            @click="work.openDiffPreview(change.path)"
          >
            <span class="min-w-0 flex-1 truncate font-mono text-[11.5px]">{{ change.path }}</span>
            <span class="shrink-0 font-mono text-[11px] font-semibold" :class="gitBadgeColor(change.status)">
              {{ change.status }}
            </span>
          </button>
        </div>
      </template>

      <WorkDiffViewer
        v-if="work.previewDiff"
        :file-path="work.previewDiff.path"
        :patch="work.previewDiff.diff"
        :additions="activeSessionDiff?.additions"
        :deletions="activeSessionDiff?.deletions"
        :can-revert="Boolean(work.gitStatus.is_repo && work.previewDiff.path !== '全部变更')"
        :can-expand="true"
        @close="work.previewDiff = null; selectedSessionDiffFile = null"
        @open-file="work.openFilePreview($event)"
        @open-explorer="work.openInExplorer($event)"
        @insert-path="emit('insertPath', $event)"
        @revert-file="handleRevertFile"
        @expand="work.diffModalOpen = true"
      />
    </div>

    <!-- Tab 4: Runtime + MCP + LSP + Formatter -->
    <div v-else class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto custom-scrollbar p-3">
      <section class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">OpenCode 服务</span>
          <span class="flex items-center gap-1.5 text-[11.5px]" :style="{ color: stateColor }">
            <span
              class="h-1.5 w-1.5 rounded-full"
              :class="{ 'work-dot-live': runtime.ready }"
              :style="{ background: stateColor }"
            />
            {{ stateLabel }}
          </span>
        </div>
        <p class="mt-2 truncate text-[13px] font-medium text-fg">
          OpenCode {{ runtime.status?.version ?? "未安装" }}
          <span v-if="runtime.status?.port" class="font-mono text-[11px] text-fg-faint">· :{{ runtime.status.port }}</span>
        </p>
        <div class="mt-3 flex flex-wrap gap-2">
          <BaseButton size="sm" variant="secondary" :loading="runtime.busy" @click="runtime.restart()">重启服务</BaseButton>
          <BaseButton size="sm" variant="ghost" @click="work.setTerminalOpen(!work.terminalOpen)">
            {{ work.terminalOpen ? "收起终端" : "打开终端" }}
          </BaseButton>
          <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-settings' })">设置</BaseButton>
        </div>
      </section>

      <!-- MCP Status Strip -->
      <section class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">MCP 服务</span>
          <button
            type="button"
            class="text-[11px] text-fg-faint hover:text-fg"
            @click="router.push({ name: 'work-settings', query: { sub: 'mcp' } })"
          >
            管理 ›
          </button>
        </div>
        <div v-if="runtime.mcpServers.length" class="mt-2 space-y-1.5">
          <div
            v-for="m in runtime.mcpServers"
            :key="m.name"
            class="flex items-center justify-between gap-2 rounded-xl bg-surface/55 px-2.5 py-1.5 text-[12px]"
          >
            <span class="truncate text-fg">{{ m.name }}</span>
            <div class="flex shrink-0 items-center gap-1">
              <button
                v-if="m.status === 'needs_auth'"
                type="button"
                class="rounded-md bg-warning-weak px-1.5 py-0.5 text-[10.5px] font-medium text-warning"
                @click="runtime.authMcpServer(m.name, work.activeWorkspace?.path)"
              >
                OAuth 鉴权
              </button>
              <button
                type="button"
                class="rounded-md px-1.5 py-0.5 text-[10.5px]"
                :style="{ color: m.status === 'connected' ? 'var(--success)' : m.status === 'failed' ? 'var(--danger)' : 'var(--fg-faint)' }"
                @click="runtime.toggleMcpServer(m.name, m.status !== 'connected', work.activeWorkspace?.path)"
              >
                {{ m.status === "connected" ? "已连接" : m.status === "disabled" ? "已停用" : m.status }}
              </button>
            </div>
          </div>
        </div>
        <p v-else class="mt-2 text-[11.5px] text-fg-faint">暂未配置 MCP 服务器</p>
      </section>

      <!-- LSP Status Strip -->
      <section class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">LSP 语言服务器</span>
          <button
            type="button"
            class="text-[11px] text-fg-faint hover:text-fg"
            @click="runtime.loadLspStatus(work.activeWorkspace?.path)"
          >
            刷新
          </button>
        </div>
        <div v-if="runtime.lspStatuses.length" class="mt-2 space-y-1">
          <div
            v-for="lsp in runtime.lspStatuses"
            :key="lsp.id"
            class="flex items-center justify-between gap-2 text-[12px] text-fg-muted"
          >
            <span class="truncate">{{ lsp.name }}</span>
            <span class="text-[10.5px]" :style="{ color: lsp.status === 'connected' ? 'var(--success)' : 'var(--danger)' }">
              {{ lsp.status === "connected" ? "已就绪" : "异常" }}
            </span>
          </div>
        </div>
        <p v-else class="mt-2 text-[11.5px] text-fg-faint">打开项目源码后自动按语言激活 LSP</p>
      </section>

      <!-- Formatter Status Strip -->
      <section v-if="runtime.formatterStatuses.length" class="rounded-2xl bg-canvas/85 p-3.5">
        <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">代码格式化器</span>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <span
            v-for="fmt in runtime.formatterStatuses"
            :key="fmt.name"
            class="rounded-lg bg-surface/75 px-2 py-0.5 text-[11px]"
            :class="fmt.enabled ? 'text-fg' : 'text-fg-faint opacity-60'"
            :title="fmt.extensions.join(', ')"
          >
            {{ fmt.name }}
          </span>
        </div>
      </section>
    </div>
  </aside>
</template>
