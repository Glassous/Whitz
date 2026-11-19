<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore, type WorkInspectorTab } from "../../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";
import WorkspaceTreeNode from "./WorkspaceTreeNode.vue";
import WorkFilePreview from "./WorkFilePreview.vue";

const emit = defineEmits<{
  insertPath: [string];
  close: [];
}>();

const router = useRouter();
const runtime = useRuntimeStore();
const work = useWorkStore();

const diffScope = ref<"session" | "git">("session");
const selectedSessionDiffFile = ref<string | null>(null);

const tabs: Array<{ key: WorkInspectorTab; label: string }> = [
  { key: "files", label: "文件" },
  { key: "git", label: "变更" },
  { key: "plan", label: "计划" },
  { key: "runtime", label: "运行" },
];

const rootEntries = computed(() => work.childrenByDir[""] ?? []);
const planItems = computed(() => {
  const items = (work.plan?.items ?? []) as Array<Record<string, unknown>>;
  return Array.isArray(items) ? items : [];
});

const activeBranch = computed(() => work.vcsBranch || work.gitStatus.branch || null);
const totalChangesBadge = computed(() => work.sessionDiffs.length || work.gitStatus.changes.length);

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
  const beforeLines = (item.before ?? "").split("\n");
  const afterLines = (item.after ?? "").split("\n");
  const unified = [
    `--- a/${item.file}`,
    `+++ b/${item.file}`,
    `@@ -1,${beforeLines.length} +1,${afterLines.length} @@`,
    ...beforeLines.slice(0, 60).map((l) => `- ${l}`),
    ...afterLines.slice(0, 80).map((l) => `+ ${l}`),
  ].join("\n");
  work.previewDiff = { path: item.file, diff: unified };
}

watch(
  () => work.inspectorTab,
  (tab) => {
    if (tab === "runtime") {
      void runtime.loadMcpServers(work.activeWorkspace?.path ?? null);
      void runtime.loadLspStatus(work.activeWorkspace?.path ?? null);
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
    <!-- Top Tabs Header (Borderless, Single-Line, Aligned with PlanPanel.vue) -->
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
            v-if="tab.key === 'git' && totalChangesBadge > 0"
            class="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-surface px-1 text-[10px] leading-none tabular-nums text-fg"
          >
            {{ totalChangesBadge }}
          </span>
          <span
            v-else-if="tab.key === 'plan' && planItems.length"
            class="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-surface px-1 text-[10px] leading-none tabular-nums text-fg"
          >
            {{ planItems.length }}
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

    <!-- Tab 1: Workspace Files -->
    <div v-if="work.inspectorTab === 'files'" class="flex min-h-0 flex-1 flex-col gap-2.5 p-3">
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
            <button type="button" class="hover:text-fg" title="由 OpenCode 自动分析生成项目 AGENTS.md" @click="work.initAgentsMd()">
              /init
            </button>
            <button type="button" class="hover:text-fg" @click="work.openInExplorer()">
              打开目录
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
          @insert-path="emit('insertPath', $event)"
        />
      </template>
    </div>

    <!-- Tab 2: Session Diff & Git Changes -->
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

        <span v-if="activeBranch" class="truncate font-mono text-[11px] text-fg-faint" :title="`当前分支: ${activeBranch}`">
          ⎇ {{ activeBranch }}
        </span>
      </div>

      <!-- Session-level Diff -->
      <template v-if="diffScope === 'session'">
        <div
          class="min-h-0 overflow-y-auto custom-scrollbar rounded-2xl bg-canvas/70 p-1.5"
          :class="work.previewDiff ? 'max-h-[40%] shrink-0' : 'flex-1'"
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
            <span class="min-w-0 flex-1 truncate">{{ item.file }}</span>
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
          :class="work.previewDiff ? 'max-h-[40%] shrink-0' : 'flex-1'"
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
            <span class="min-w-0 flex-1 truncate">{{ change.path }}</span>
            <span class="shrink-0 font-mono text-[11px] font-semibold" :class="gitBadgeColor(change.status)">
              {{ change.status }}
            </span>
          </button>
        </div>
      </template>

      <WorkFilePreview
        v-if="work.previewDiff"
        :diff="work.previewDiff"
        @close="work.previewDiff = null; selectedSessionDiffFile = null"
        @open-explorer="work.openInExplorer($event)"
        @insert-path="emit('insertPath', $event)"
      />
    </div>

    <!-- Tab 3: Plan & Subagents -->
    <div v-else-if="work.inspectorTab === 'plan'" class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto custom-scrollbar p-3">
      <section class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">任务计划</span>
          <span class="text-[11px] text-fg-faint">{{ planItems.length }} 步</span>
        </div>
        <ol v-if="planItems.length" class="mt-2.5 space-y-2">
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
        <p v-else class="mt-2.5 text-[12px] leading-relaxed text-fg-faint">
          复杂编码或研究任务会自动拆解步骤，进度会实时同步到这里。
        </p>
      </section>

      <section v-if="work.subagents.length" class="rounded-2xl bg-canvas/85 p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">子代理委派</span>
          <span class="text-[11px] text-fg-faint">{{ work.subagents.length }}</span>
        </div>
        <div class="mt-2.5 space-y-2">
          <div v-for="sub in work.subagents" :key="sub.id" class="rounded-xl bg-surface/65 px-3 py-2 text-[12px]">
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-fg">{{ sub.goal }}</span>
              <span class="text-[10.5px] text-fg-faint">{{ sub.status }}</span>
            </div>
            <p v-if="sub.summary" class="mt-1 text-[11.5px] text-fg-muted">{{ sub.summary }}</p>
          </div>
        </div>
      </section>
    </div>

    <!-- Tab 4: Runtime + MCP + LSP + Context Compact -->
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
          <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-settings' })">Work 设置</BaseButton>
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
            <button
              type="button"
              class="shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px]"
              :style="{ color: m.status === 'connected' ? 'var(--success)' : m.status === 'failed' ? 'var(--danger)' : 'var(--fg-faint)' }"
              @click="runtime.toggleMcpServer(m.name, m.status !== 'connected', work.activeWorkspace?.path)"
            >
              {{ m.status === "connected" ? "已连接" : m.status === "disabled" ? "已停用" : m.status }}
            </button>
          </div>
        </div>
        <p v-else class="mt-2 text-[11.5px] text-fg-faint">暂未配置 MCP 服务器</p>
      </section>

      <!-- LSP Status Strip -->
      <section v-if="runtime.lspStatuses.length" class="rounded-2xl bg-canvas/85 p-3.5">
        <span class="text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">LSP 语言服务器</span>
        <div class="mt-2 space-y-1">
          <div
            v-for="lsp in runtime.lspStatuses"
            :key="lsp.id"
            class="flex items-center justify-between gap-2 text-[12px] text-fg-muted"
          >
            <span class="truncate">{{ lsp.name }}</span>
            <span class="text-[10.5px]" :style="{ color: lsp.status === 'connected' ? 'var(--success)' : 'var(--danger)' }">
              {{ lsp.status }}
            </span>
          </div>
        </div>
      </section>
    </div>
  </aside>
</template>
