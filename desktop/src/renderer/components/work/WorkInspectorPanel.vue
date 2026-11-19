<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useDesktopStore } from "../../stores/desktop";
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
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();

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

const stateLabel = computed(() => {
  const state = runtime.status?.state;
  return (
    {
      ready: "运行中",
      starting: "启动中",
      installing: "安装中",
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

const sourceLabel = computed(() => {
  const s = runtime.status?.source;
  if (s === "custom") return "自定义路径";
  if (s === "npm") return "本机 npm (opencode-ai)";
  if (s === "scoop") return "本机 Scoop";
  if (s === "winget") return "本机 WinGet";
  if (s === "system") return "本机环境";
  return "未探测";
});

function gitBadgeColor(status: string): string {
  if (status.includes("?")) return "text-success";
  if (status.includes("D")) return "text-danger";
  return "text-warning";
}
</script>

<template>
  <aside class="flex h-full w-full flex-col border-l border-line bg-sidebar/55">
    <!-- Tabs Header -->
    <div class="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-line px-3">
      <div class="flex items-center gap-1 rounded-xl bg-surface/70 p-0.5">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          type="button"
          class="focus-ring relative rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors"
          :class="work.inspectorTab === tab.key ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
          @click="work.inspectorTab = tab.key"
        >
          {{ tab.label }}
          <span
            v-if="tab.key === 'git' && work.gitStatus.changes.length"
            class="ml-1 rounded-full bg-surface px-1.5 py-0.2 text-[10px] tabular-nums text-fg"
          >
            {{ work.gitStatus.changes.length }}
          </span>
          <span
            v-else-if="tab.key === 'plan' && planItems.length"
            class="ml-1 rounded-full bg-surface px-1.5 py-0.2 text-[10px] tabular-nums text-fg"
          >
            {{ planItems.length }}
          </span>
        </button>
      </div>

      <div class="flex items-center gap-1">
        <button
          v-if="work.activeWorkspace && (work.inspectorTab === 'files' || work.inspectorTab === 'git')"
          type="button"
          class="focus-ring rounded-lg p-1.5 text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          title="刷新工作区"
          @click="work.refreshWorkspace()"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6" />
          </svg>
        </button>
        <button
          type="button"
          class="focus-ring rounded-lg p-1.5 text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          title="收起工作台面板"
          @click="emit('close')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Tab 1: Files -->
    <div v-if="work.inspectorTab === 'files'" class="flex min-h-0 flex-1 flex-col gap-2.5 p-3">
      <div v-if="!work.activeWorkspace" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-line bg-canvas/50 p-6 text-center">
        <p class="text-[13px] font-medium text-fg">尚未选择本地工作区</p>
        <p class="mt-1.5 text-[12px] leading-relaxed text-fg-faint">
          选择一个本地项目文件夹后，可在此浏览项目结构、预览源码，并让 OpenCode 直接读写代码。
        </p>
        <BaseButton size="sm" class="mt-4" @click="work.pickWorkspace()">选择本地文件夹</BaseButton>
      </div>

      <template v-else>
        <div class="flex items-center justify-between gap-2 px-1">
          <span class="truncate text-[11.5px] font-medium text-fg-muted" :title="work.activeWorkspace.path">
            {{ work.activeWorkspace.name }}
          </span>
          <button
            type="button"
            class="shrink-0 text-[11px] text-fg-faint hover:text-fg"
            @click="work.openInExplorer()"
          >
            打开目录
          </button>
        </div>

        <div
          class="min-h-0 overflow-y-auto custom-scrollbar rounded-xl border border-line bg-canvas/70 p-1.5"
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

    <!-- Tab 2: Git Changes -->
    <div v-else-if="work.inspectorTab === 'git'" class="flex min-h-0 flex-1 flex-col gap-2.5 p-3">
      <div v-if="!work.activeWorkspace" class="flex flex-1 items-center justify-center p-6 text-center text-[12.5px] text-fg-faint">
        请先在侧栏选择本地工作区文件夹。
      </div>
      <div v-else-if="!work.gitStatus.is_repo" class="flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-line bg-canvas/50 p-6 text-center">
        <p class="text-[13px] font-medium text-fg">当前目录不是 Git 仓库</p>
        <p class="mt-1 text-[12px] text-fg-faint">仅 Git 仓库支持查看工作区 Diff 变更记录。</p>
      </div>
      <template v-else>
        <div class="flex items-center justify-between px-1 text-[12px]">
          <span class="text-fg-muted">
            分支：<strong class="font-medium text-fg">{{ work.gitStatus.branch ?? "HEAD" }}</strong>
          </span>
          <button
            v-if="work.gitStatus.changes.length"
            type="button"
            class="text-[11px] font-medium"
            style="color: var(--work-accent)"
            @click="work.openDiffPreview()"
          >
            查看全部 Diff
          </button>
        </div>

        <div
          class="min-h-0 overflow-y-auto custom-scrollbar rounded-xl border border-line bg-canvas/70 p-1.5"
          :class="work.previewDiff ? 'max-h-[38%] shrink-0' : 'flex-1'"
        >
          <div v-if="!work.gitStatus.changes.length" class="p-4 text-center text-[12px] text-fg-faint">
            工作区干净，暂无未提交改动
          </div>
          <button
            v-for="change in work.gitStatus.changes"
            :key="`${change.staged}-${change.path}`"
            type="button"
            class="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-hover"
            :class="work.previewDiff?.path === change.path ? 'bg-active text-fg font-medium' : 'text-fg-muted'"
            @click="work.openDiffPreview(change.path)"
          >
            <span class="min-w-0 flex-1 truncate">{{ change.path }}</span>
            <span class="shrink-0 font-mono text-[11px] font-semibold" :class="gitBadgeColor(change.status)">
              {{ change.status }}
            </span>
          </button>
        </div>

        <WorkFilePreview
          v-if="work.previewDiff"
          :diff="work.previewDiff"
          @close="work.previewDiff = null"
          @open-explorer="work.openInExplorer($event)"
          @insert-path="emit('insertPath', $event)"
        />
      </template>
    </div>

    <!-- Tab 3: Plan & Subagents -->
    <div v-else-if="work.inspectorTab === 'plan'" class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto custom-scrollbar p-3">
      <section class="rounded-2xl border border-line bg-canvas p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">任务计划</span>
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
            ></span>
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

      <section v-if="work.subagents.length" class="rounded-2xl border border-line bg-canvas p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">子智能体委派</span>
          <span class="text-[11px] text-fg-faint">{{ work.subagents.length }}</span>
        </div>
        <div class="mt-2.5 space-y-2">
          <div
            v-for="sub in work.subagents"
            :key="sub.id"
            class="rounded-xl border border-line bg-surface/40 px-3 py-2 text-[12px]"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-fg">{{ sub.goal }}</span>
              <span class="text-[10.5px] text-fg-faint">{{ sub.status }}</span>
            </div>
            <p v-if="sub.summary" class="mt-1 text-[11.5px] text-fg-muted">{{ sub.summary }}</p>
          </div>
        </div>
      </section>
    </div>

    <!-- Tab 4: Runtime -->
    <div v-else class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto custom-scrollbar p-3">
      <section class="rounded-2xl border border-line bg-canvas p-3.5">
        <div class="flex items-center justify-between">
          <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">本地运行时</span>
          <span class="flex items-center gap-1.5 text-[11.5px]" :style="{ color: stateColor }">
            <span
              class="h-1.5 w-1.5 rounded-full"
              :class="{ 'work-dot-live': runtime.ready }"
              :style="{ background: stateColor }"
            ></span>
            {{ stateLabel }}
          </span>
        </div>
        <p class="mt-2.5 truncate text-[13px] font-medium text-fg" :title="runtime.status?.exe_path ?? ''">
          OpenCode {{ runtime.status?.version ?? "未安装" }}
        </p>
        <p class="mt-0.5 truncate text-[11.5px] text-fg-faint">
          来源：{{ sourceLabel }} · {{ runtime.status?.model || "未选择模型" }}
          <span v-if="runtime.status?.port"> · :{{ runtime.status.port }}</span>
        </p>
        <p v-if="runtime.gateway?.base_url" class="mt-1 truncate font-mono text-[11px] text-fg-muted" :title="runtime.gateway.base_url">
          Whitz 本机网关：{{ runtime.gateway.base_url }}
        </p>
        <p v-if="runtime.status?.workspace_path" class="mt-1 truncate text-[11px] text-fg-muted" :title="runtime.status.workspace_path">
          工作目录：{{ runtime.status.workspace_path }}
        </p>

        <div class="mt-3 flex flex-wrap gap-2">
          <BaseButton size="sm" variant="secondary" :loading="runtime.busy" @click="runtime.restart()">重启服务</BaseButton>
          <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-settings' })">Work 设置</BaseButton>
        </div>
        <p v-if="runtime.status?.detail" class="mt-2 text-[11.5px] text-warning">{{ runtime.status.detail }}</p>
      </section>

      <section class="rounded-2xl border border-line bg-canvas p-3.5">
        <span class="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-faint">数据隔离与额度</span>
        <p class="mt-2 break-all text-[11.5px] leading-relaxed text-fg-muted">
          数据目录：{{ runtime.status?.home_dir ?? "—" }}
        </p>
        <p class="mt-1.5 text-[11.5px] leading-relaxed text-fg-faint">
          对话、工作区、记忆与技能均保存在本机，与 Chat 完全独立；仅选择「Whitz 内置」模型时与 Chat 共享账号额度。
        </p>
        <p v-if="!desktop.loggedIn" class="mt-2 text-[11.5px] text-warning">
          当前未登录：内置模型不可用，可通过自带 Key 正常运行。
        </p>
      </section>
    </div>
  </aside>
</template>
