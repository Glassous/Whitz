<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import type { WorkAttachment } from "@shared/work-types";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkStore } from "../stores/work";
import WorkSidebar from "../components/work/WorkSidebar.vue";
import WorkMessageList from "../components/work/WorkMessageList.vue";
import WorkComposer from "../components/work/WorkComposer.vue";
import WorkInspectorPanel from "../components/work/WorkInspectorPanel.vue";
import ApprovalSheet from "../components/work/ApprovalSheet.vue";
import BaseButton from "@web/components/ui/BaseButton.vue";

const PANEL_WIDTH_STORAGE_KEY = "whitz_work_panel_width";
const DEFAULT_PANEL_WIDTH = 360;
const MIN_PANEL_WIDTH = 320;
const MAX_PANEL_WIDTH = 620;

const router = useRouter();
const runtime = useRuntimeStore();
const work = useWorkStore();

const composerRef = ref<InstanceType<typeof WorkComposer> | null>(null);
const messageListRef = ref<InstanceType<typeof WorkMessageList> | null>(null);

const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(false);
const drawerDragProgress = ref<number | null>(null);

const showInspector = computed({
  get: () => work.inspectorOpen,
  set: (v: boolean) => work.setInspectorOpen(v),
});
const mobileInspectorOpen = ref(false);

function loadPanelWidth(): number {
  if (typeof window === "undefined") return DEFAULT_PANEL_WIDTH;
  const raw = Number(window.localStorage.getItem(PANEL_WIDTH_STORAGE_KEY));
  return Number.isFinite(raw) ? Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, raw)) : DEFAULT_PANEL_WIDTH;
}

const panelWidth = ref<number>(loadPanelWidth());
const isResizingPanel = ref(false);
let resizeStartX = 0;
let resizeStartWidth = DEFAULT_PANEL_WIDTH;
let mediaQuery: MediaQueryList | null = null;

function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
  if (e.matches) sidebarOpen.value = false;
}

function onSidebarToggleClick() {
  if (isDesktop.value) sidebarCollapsed.value = !sidebarCollapsed.value;
  else sidebarOpen.value = !sidebarOpen.value;
}

function onInspectorToggleClick() {
  if (window.innerWidth >= 1024) {
    showInspector.value = !showInspector.value;
  } else {
    mobileInspectorOpen.value = !mobileInspectorOpen.value;
  }
}

function clampPanelWidth(w: number): number {
  const maxByViewport = typeof window !== "undefined" ? Math.max(MIN_PANEL_WIDTH, window.innerWidth - 420) : MAX_PANEL_WIDTH;
  return Math.round(Math.min(Math.min(MAX_PANEL_WIDTH, maxByViewport), Math.max(MIN_PANEL_WIDTH, w)));
}

function onResizePointerDown(e: PointerEvent) {
  if (!showInspector.value) return;
  const target = e.currentTarget as HTMLElement;
  target.setPointerCapture(e.pointerId);
  isResizingPanel.value = true;
  resizeStartX = e.clientX;
  resizeStartWidth = panelWidth.value;
}

function onResizePointerMove(e: PointerEvent) {
  if (!isResizingPanel.value) return;
  panelWidth.value = clampPanelWidth(resizeStartWidth + (resizeStartX - e.clientX));
}

function onResizePointerUp(e: PointerEvent) {
  if (!isResizingPanel.value) return;
  isResizingPanel.value = false;
  const target = e.currentTarget as HTMLElement;
  if (target.hasPointerCapture(e.pointerId)) target.releasePointerCapture(e.pointerId);
  try {
    window.localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(panelWidth.value));
  } catch {
    /* ignore */
  }
}

const currentProjectName = computed(() => {
  const p = work.current?.conversation.workspace_path || work.activeWorkspace?.path;
  if (!p) return null;
  return p.split(/[\\/]/).filter(Boolean).pop() || p;
});

const composerDisabled = computed(() => !runtime.installed || runtime.status?.state === "disabled");

const statusSummary = computed(() => {
  const s = runtime.status?.state;
  if (!runtime.installed) return { label: "需安装 OpenCode", tone: "var(--warning)" };
  if (s === "ready") return { label: "就绪", tone: "var(--success)" };
  if (s === "starting") return { label: "启动中", tone: "var(--warning)" };
  if (s === "error") return { label: "连接异常", tone: "var(--danger)" };
  return { label: "未运行", tone: "var(--fg-faint)" };
});

const usageLabel = computed(() => {
  const u = work.usage;
  if (!u || !u.total) return "";
  const formatted = u.total >= 1000 ? `${(u.total / 1000).toFixed(1)}k` : String(u.total);
  if (u.context_limit && u.context_limit > 0) {
    const pct = Math.min(100, Math.round((u.total / u.context_limit) * 100));
    return `${formatted} tokens (${pct}%)`;
  }
  return `${formatted} tokens`;
});

async function handleSend(payload: {
  text: string;
  skills: string[];
  attachments: WorkAttachment[];
  modelRef: string | null;
  agentName: string | null;
  variant: string | null;
}) {
  try {
    await work.send(payload.text, {
      skillNames: payload.skills,
      attachments: payload.attachments,
      modelRef: payload.modelRef,
      agentName: payload.agentName,
      variant: payload.variant,
    });
  } catch (err) {
    work.error = err instanceof Error ? err.message : "发送失败";
  }
}

async function handleCommand(cmd: { name: string; args: string }) {
  try {
    if (cmd.name === "compact") {
      await work.compact(work.current?.conversation.model_ref);
      return;
    }
    if (cmd.name === "undo") {
      const lastUser = [...work.messages].reverse().find((m) => m.role === "user");
      if (lastUser) await work.revert(lastUser.id);
      return;
    }
    if (cmd.name === "redo") {
      await work.unrevert();
      return;
    }
    if (cmd.name === "fork") {
      await work.fork();
      return;
    }
    if (cmd.name === "init") {
      await work.initAgentsMd(work.current?.conversation.model_ref);
      return;
    }
    await work.runSlashCommand(cmd.name, cmd.args, {
      modelRef: work.current?.conversation.model_ref,
      agentName: work.current?.conversation.agent_name,
      variant: work.current?.conversation.variant,
    });
  } catch (err) {
    work.error = err instanceof Error ? err.message : "指令执行失败";
  }
}

async function handleShell(cmd: string) {
  try {
    await work.runShellCommand(cmd, {
      agentName: work.current?.conversation.agent_name,
      modelRef: work.current?.conversation.model_ref,
    });
  } catch (err) {
    work.error = err instanceof Error ? err.message : "命令执行失败";
  }
}

async function handleRevert(messageId: string) {
  try {
    await work.revert(messageId);
  } catch (err) {
    work.error = err instanceof Error ? err.message : "撤回失败";
  }
}

async function handleFork(messageId: string) {
  try {
    await work.fork(messageId);
  } catch (err) {
    work.error = err instanceof Error ? err.message : "分支对话失败";
  }
}

function handleOpenSteps(messageId: string) {
  work.selectTurn(messageId);
  if (isDesktop.value) {
    showInspector.value = true;
  } else {
    mobileInspectorOpen.value = true;
  }
}

function handleInsertPath(relPath: string) {
  composerRef.value?.insertPath(relPath);
}

onMounted(async () => {
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  work.bindEvents();
  await runtime.init().catch(() => undefined);
  await Promise.all([work.loadWorkspaceState(), work.loadList(), work.syncActiveRuns()]);
  if (!work.current && work.conversations.length) {
    await work.select(work.conversations[0].id).catch(() => undefined);
  }
});

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener("change", onMediaChange);
});
</script>

<template>
  <div class="relative flex h-full w-full overflow-hidden bg-canvas text-fg">
    <!-- Mobile Sidebar Backdrop -->
    <Transition
      enter-active-class="transition duration-250 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="sidebarOpen"
        class="fixed inset-0 z-30 bg-black/40 md:hidden"
        :style="drawerDragProgress !== null ? { opacity: drawerDragProgress, transition: 'none' } : undefined"
        @click="sidebarOpen = false"
      />
    </Transition>

    <WorkSidebar
      :open="sidebarOpen"
      :collapsed="sidebarCollapsed"
      @close="sidebarOpen = false"
      @drag-progress="drawerDragProgress = $event"
    />

    <main class="relative flex min-w-0 flex-1 overflow-hidden">
      <!-- Fixed Right Panel Toggle (Matches ChatView.vue exact top-right icon) -->
      <button
        type="button"
        class="focus-ring absolute right-3.5 top-3.5 z-30 inline-flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
        :aria-label="showInspector ? '收起工作台面板' : '展开工作台面板'"
        :title="showInspector ? '收起工作台面板' : '展开工作台面板'"
        @click="onInspectorToggleClick"
      >
        <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 5h18v14H3zM15 5v14" />
        </svg>
        <span
          v-if="(work.sessionDiffs.length || work.gitStatus.changes.length) && !showInspector"
          class="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-accent"
          aria-hidden="true"
        />
      </button>

      <!-- Main Conversation Column (Matches ChatView.vue, Non-overlapping Clean Header) -->
      <div class="relative flex min-w-0 flex-1 flex-col">
        <header class="relative z-20 flex h-13 shrink-0 items-center gap-2.5 bg-canvas px-3.5" :class="showInspector ? 'pr-4' : 'pr-14'">
          <button
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
            :aria-label="sidebarCollapsed ? '展开侧栏' : '切换侧栏'"
            @click="onSidebarToggleClick"
          >
            <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" d="M4 8.5h16M4 15.5h10" />
            </svg>
          </button>

          <h1 class="min-w-0 flex-1 truncate text-[15px] font-semibold text-fg">
            {{ work.current?.conversation.title ?? "OpenCode 工作台" }}
          </h1>

          <!-- Minimal Live Status & Context Telemetry -->
          <div class="flex shrink-0 items-center gap-2">
            <button
              v-if="usageLabel"
              type="button"
              class="hidden whitespace-nowrap rounded-full bg-surface/80 px-2.5 py-1 text-[11px] tabular-nums text-fg-faint transition-colors hover:text-fg sm:inline"
              title="点击压缩当前上下文 (/compact)"
              @click="handleCommand({ name: 'compact', args: '' })"
            >
              {{ usageLabel }} · 压缩
            </button>

            <button
              v-if="!runtime.ready || !runtime.installed"
              type="button"
              class="flex whitespace-nowrap items-center gap-1.5 rounded-full bg-surface/85 px-2.5 py-1 text-[11.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              @click="router.push({ name: runtime.installed ? 'work-settings' : 'work-setup' })"
            >
              <span class="h-1.5 w-1.5 rounded-full" :style="{ background: statusSummary.tone }" />
              <span>{{ statusSummary.label }}</span>
            </button>
          </div>
        </header>

        <!-- Runtime Setup Notice -->
        <div
          v-if="!runtime.installed"
          class="mx-auto mt-2 flex w-full max-w-4xl items-center justify-between gap-3 rounded-2xl bg-surface px-4 py-2.5 text-[12.5px] text-fg-muted"
        >
          <span>尚未检测到本机 OpenCode CLI，安装或指定路径后即可使用 Work。</span>
          <BaseButton size="sm" @click="router.push({ name: 'work-setup' })">配置指引</BaseButton>
        </div>

        <!-- Message List -->
        <WorkMessageList
          ref="messageListRef"
          :conversation-id="work.activeConversationId"
          :messages="work.messages"
          :active-assistant-id="work.activeAssistantId"
          :selected-turn-id="work.selectedTurnId"
          :streaming="work.streaming"
          :reverted-count="work.current?.reverted_count ?? 0"
          :project-name="currentProjectName"
          @open-file="work.openFilePreview"
          @revert="handleRevert"
          @unrevert="work.unrevert()"
          @fork="handleFork"
          @steps="handleOpenSteps"
        />

        <!-- Progressive Blur Bottom + Inline Approvals + Error + Composer (Aligned with ChatView.vue) -->
        <div class="progressive-blur-bottom pointer-events-none absolute inset-x-0 bottom-0 z-10 h-24 sm:h-28" />
        <div class="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-transparent px-3 pb-4 pt-2 sm:px-6 sm:pb-5">
          <div class="pointer-events-auto mx-auto w-full max-w-4xl space-y-2.5">
            <ApprovalSheet
              v-if="work.pendingControl"
              :kind="work.pendingControl.kind"
              :tool="work.pendingControl.tool"
              :preview="work.pendingControl.preview"
              :choices="work.pendingControl.choices"
              :queue-count="work.pendingCount"
              @approve="work.approve"
              @clarify="work.clarify"
            />

            <div
              v-if="work.error"
              class="flex items-center justify-between gap-3 rounded-2xl bg-danger-weak px-3.5 py-2 text-[12.5px] text-danger"
            >
              <span class="min-w-0 flex-1 truncate">{{ work.error }}</span>
              <button type="button" class="shrink-0 opacity-75 hover:opacity-100" @click="work.error = null">关闭</button>
            </div>

            <WorkComposer
              ref="composerRef"
              :streaming="work.streaming"
              :disabled="composerDisabled"
              :model-ref="work.current?.conversation.model_ref ?? null"
              :agent-name="work.current?.conversation.agent_name ?? null"
              :variant="work.current?.conversation.variant ?? null"
              @send="handleSend"
              @steer="work.steer"
              @stop="work.stop"
              @command="handleCommand"
              @shell="handleShell"
              @update:prefs="work.setSessionPrefs"
            />
          </div>
        </div>
      </div>

      <!-- Desktop Resizable Right Inspector Panel (Matches ChatView.vue PlanPanel aside) -->
      <aside
        class="relative hidden h-full shrink-0 overflow-hidden bg-sidebar lg:block"
        :class="[
          showInspector ? 'opacity-100' : 'pointer-events-none opacity-0',
          isResizingPanel ? 'transition-none' : 'transition-[width,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]',
        ]"
        :style="{ width: showInspector ? `${panelWidth}px` : '0px' }"
        :aria-hidden="!showInspector"
      >
        <div
          v-if="showInspector"
          role="separator"
          tabindex="0"
          aria-orientation="vertical"
          aria-label="调整工作台面板宽度"
          class="group absolute inset-y-0 left-0 z-30 flex w-2.5 cursor-col-resize touch-none select-none items-center justify-center transition-colors hover:bg-hover/60"
          @pointerdown="onResizePointerDown"
          @pointermove="onResizePointerMove"
          @pointerup="onResizePointerUp"
          @pointercancel="onResizePointerUp"
        >
          <span
            class="h-10 w-0.5 rounded-full transition-colors"
            :class="isResizingPanel ? 'bg-accent' : 'bg-transparent group-hover:bg-line-strong'"
          />
        </div>
        <div class="h-full" :style="{ width: `${panelWidth}px` }">
          <WorkInspectorPanel
            @insert-path="handleInsertPath"
            @close="showInspector = false"
          />
        </div>
      </aside>
    </main>

    <!-- Mobile Inspector Drawer -->
    <Transition
      enter-active-class="transition duration-250 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="mobileInspectorOpen" class="fixed inset-0 z-40 lg:hidden">
        <div class="absolute inset-0 bg-black/40" @click="mobileInspectorOpen = false" />
        <div class="absolute inset-y-0 right-0 w-[min(360px,90dvw)] bg-sidebar shadow-2xl">
          <WorkInspectorPanel
            @insert-path="handleInsertPath"
            @close="mobileInspectorOpen = false"
          />
        </div>
      </div>
    </Transition>
  </div>
</template>
