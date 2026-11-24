<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import type { WorkApprovalChoice, WorkAttachment } from "@shared/work-types";
import { buildFallbackPatch } from "../lib/unifiedDiff";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkStore } from "../stores/work";
import WorkSidebar from "../components/work/WorkSidebar.vue";
import WorkMessageList from "../components/work/WorkMessageList.vue";
import WorkComposer from "../components/work/WorkComposer.vue";
import WorkInspectorPanel from "../components/work/WorkInspectorPanel.vue";
import WorkTerminalDock from "../components/work/WorkTerminalDock.vue";
import WorkCommandPalette from "../components/work/WorkCommandPalette.vue";
import WorkDiffViewer from "../components/work/WorkDiffViewer.vue";
import ApprovalSheet from "../components/work/ApprovalSheet.vue";
import BaseButton from "@web/components/ui/BaseButton.vue";
import BaseModal from "@web/components/ui/BaseModal.vue";
import ScrollToBottomButton from "@web/components/ui/ScrollToBottomButton.vue";

const PANEL_WIDTH_STORAGE_KEY = "whitz_work_panel_width";
const DEFAULT_PANEL_WIDTH = 360;
const MIN_PANEL_WIDTH = 320;
const MAX_PANEL_WIDTH = 640;

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();

const composerRef = ref<InstanceType<typeof WorkComposer> | null>(null);
const messageListRef = ref<InstanceType<typeof WorkMessageList> | null>(null);
const bottomOverlayRef = ref<HTMLElement | null>(null);
const bottomOverlayHeight = ref(0);
let bottomOverlayObserver: ResizeObserver | null = null;

const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
const sidebarOpen = ref(false);
const drawerDragProgress = ref<number | null>(null);

// Shared persistent sidebar collapsed state with ChatView.vue
const sidebarCollapsed = computed({
  get: () => desktop.sidebarCollapsed,
  set: (v: boolean) => desktop.setSidebarCollapsed(v),
});

const showInspector = computed({
  get: () => work.inspectorOpen,
  set: (v: boolean) => work.setInspectorOpen(v),
});
const mobileInspectorOpen = ref(false);

// Modals: Remote CLI Sessions Import & Full-screen Diff Review
const remoteSessionsModalOpen = ref(false);
const remoteSessionsDir = ref<string | null>(null);
const importingSessionId = ref<string | null>(null);
const shareNotice = ref<string | null>(null);
const diffDialogRef = ref<HTMLDialogElement | null>(null);
const modalSelectedDiffFile = ref<string | null>(null);

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
  const costPart = u.cost > 0 ? ` · $${u.cost.toFixed(4)}` : "";
  if (u.context_limit && u.context_limit > 0) {
    const pct = Math.min(100, Math.round((u.total / u.context_limit) * 100));
    return `${formatted} (${pct}%)${costPart}`;
  }
  return `${formatted} tokens${costPart}`;
});

const activeModalDiffPatch = computed(() => {
  const targetFile = modalSelectedDiffFile.value || work.previewDiff?.path || work.sessionDiffs[0]?.file || null;
  if (!targetFile) return null;
  const fromSession = work.sessionDiffs.find((d) => d.file === targetFile);
  if (fromSession) {
    return {
      file: fromSession.file,
      patch: fromSession.patch?.trim()
        ? fromSession.patch
        : buildFallbackPatch(fromSession.file, fromSession.before ?? "", fromSession.after ?? ""),
      additions: fromSession.additions,
      deletions: fromSession.deletions,
    };
  }
  if (work.previewDiff && work.previewDiff.path === targetFile) {
    return { file: work.previewDiff.path, patch: work.previewDiff.diff };
  }
  return null;
});

function showNotice(msg: string) {
  shareNotice.value = msg;
  setTimeout(() => {
    if (shareNotice.value === msg) shareNotice.value = null;
  }, 3000);
}

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

async function handleApprove(payload: { choice: WorkApprovalChoice; message?: string }) {
  try {
    await work.approve(payload.choice, payload.message);
  } catch (err) {
    work.error = err instanceof Error ? err.message : "提交审批失败";
  }
}

async function handleClarify(answers: string[][]) {
  try {
    await work.clarify(answers);
  } catch (err) {
    work.error = err instanceof Error ? err.message : "提交回答失败";
  }
}

async function handleRejectClarify() {
  try {
    await work.rejectClarify();
  } catch (err) {
    work.error = err instanceof Error ? err.message : "跳过提问失败";
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

async function handleShareToggle() {
  if (!work.current) return;
  try {
    if (work.current.conversation.share_url) {
      await navigator.clipboard.writeText(work.current.conversation.share_url).catch(() => undefined);
      showNotice(`已复制分享链接：${work.current.conversation.share_url}`);
      return;
    }
    const url = await work.shareCurrent();
    if (url) {
      await navigator.clipboard.writeText(url).catch(() => undefined);
      showNotice(`已生成并复制分享链接：${url}`);
    }
  } catch (err) {
    work.error = err instanceof Error ? err.message : "生成分享链接失败";
  }
}

async function openRemoteSessions(workspacePath?: string | null) {
  remoteSessionsDir.value = workspacePath ?? work.activeWorkspace?.path ?? null;
  remoteSessionsModalOpen.value = true;
  await work.loadRemoteSessions(remoteSessionsDir.value).catch(() => undefined);
}

async function handleImportRemote(sessionId: string) {
  importingSessionId.value = sessionId;
  try {
    await work.importRemoteSession(sessionId, remoteSessionsDir.value);
    remoteSessionsModalOpen.value = false;
    showNotice("已导入并关联 OpenCode CLI 会话");
  } catch (err) {
    work.error = err instanceof Error ? err.message : "导入会话失败";
  } finally {
    importingSessionId.value = null;
  }
}

async function handleCreateWorktree(workspacePath?: string | null) {
  const target = workspacePath ?? work.activeWorkspace?.path;
  if (!target) {
    work.error = "请先选择一个 Git 项目文件夹后再创建隔离 Worktree";
    return;
  }
  try {
    const res = await work.createWorktreeTask(target);
    showNotice(`已创建隔离 Worktree：${res.worktree.branch || res.worktree.name}`);
  } catch (err) {
    work.error = err instanceof Error ? err.message : "创建 Git Worktree 失败（请确认项目为 Git 仓库）";
  }
}

async function handleSendToChat(content: string) {
  if (!content.trim()) return;
  try {
    await navigator.clipboard.writeText(content).catch(() => undefined);
    showNotice("已复制回答并切换到云端 Chat，可直接粘贴继续讨论");
    void router.push({ name: "chat", query: { new: "1" } });
  } catch {
    void router.push({ name: "chat" });
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

function onGlobalKeydown(e: KeyboardEvent) {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if (work.commandPaletteOpen && work.commandPaletteMode === "commands") work.closeCommandPalette();
    else work.openCommandPalette("commands");
    return;
  }
  if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "p") {
    e.preventDefault();
    work.openCommandPalette("files");
    return;
  }
  if (mod && e.shiftKey && !e.altKey && e.key.toLowerCase() === "f") {
    e.preventDefault();
    work.openCommandPalette("search");
    return;
  }
  if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
    e.preventDefault();
    onSidebarToggleClick();
    return;
  }
  if (mod && !e.shiftKey && !e.altKey && (e.key === "`" || e.code === "Backquote")) {
    e.preventDefault();
    work.setTerminalOpen(!work.terminalOpen);
    return;
  }
  if (mod && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "n") {
    e.preventDefault();
    void work.create();
    return;
  }
  if (e.key === "Escape" && work.streaming && !work.commandPaletteOpen && !work.diffModalOpen && !remoteSessionsModalOpen.value) {
    const activeEl = document.activeElement;
    if (!activeEl || activeEl === document.body) {
      e.preventDefault();
      void work.stop();
    }
  }
}

// Native modal dialog sync for Full-Screen Diff Reviewer
function onDiffDialogClose() {
  if (diffDialogRef.value) diffDialogRef.value.returnValue = "";
  if (work.diffModalOpen) work.diffModalOpen = false;
}

watch(
  () => work.diffModalOpen,
  (open) => {
    const dlg = diffDialogRef.value;
    if (!dlg) return;
    if (open) {
      modalSelectedDiffFile.value = work.previewDiff?.path || work.sessionDiffs[0]?.file || null;
      if (!dlg.open) dlg.showModal();
    } else if (dlg.open) {
      dlg.close();
    }
  },
);

onMounted(async () => {
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
    window.addEventListener("keydown", onGlobalKeydown);
  }
  desktop.syncSidebarCollapsedFromStorage();
  work.bindEvents();
  work.setFocusConversationHandler(() => {
    if (router.currentRoute.value.name !== "work") {
      void router.push({ name: "work" });
    }
  });
  await runtime.init().catch(() => undefined);
  await Promise.all([work.loadWorkspaceState(), work.loadList(), work.syncActiveRuns()]);
  if (!work.current && work.conversations.length) {
    await work.select(work.conversations[0].id).catch(() => undefined);
  }
});

watch(bottomOverlayRef, (el, prev) => {
  if (prev && bottomOverlayObserver) bottomOverlayObserver.unobserve(prev);
  if (el) {
    bottomOverlayHeight.value = el.offsetHeight;
    if (typeof ResizeObserver !== "undefined") {
      if (!bottomOverlayObserver) {
        bottomOverlayObserver = new ResizeObserver((entries) => {
          const h = entries[0]?.borderBoxSize?.[0]?.blockSize ?? el.offsetHeight;
          bottomOverlayHeight.value = Math.round(h);
        });
      }
      bottomOverlayObserver.observe(el);
    }
  } else {
    bottomOverlayHeight.value = 0;
  }
});

onBeforeUnmount(() => {
  bottomOverlayObserver?.disconnect();
  bottomOverlayObserver = null;
  mediaQuery?.removeEventListener("change", onMediaChange);
  window.removeEventListener("keydown", onGlobalKeydown);
  work.setFocusConversationHandler(null);
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
      @open-remote-sessions="openRemoteSessions"
      @create-worktree="handleCreateWorktree"
    />

    <main class="relative flex min-w-0 flex-1 overflow-hidden">
      <!-- Fixed Right Panel Toggle -->
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

      <!-- Main Column (Header + Message List + Composer + Optional Bottom Terminal Dock) -->
      <div class="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <header
          class="relative z-20 flex h-13 shrink-0 items-center gap-2 bg-canvas px-3.5"
          :class="showInspector ? 'pr-4' : 'pr-14'"
        >
          <button
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
            :aria-label="sidebarCollapsed ? '展开侧栏 (Ctrl+B)' : '收起侧栏 (Ctrl+B)'"
            title="切换侧栏 (Ctrl+B)"
            @click="onSidebarToggleClick"
          >
            <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" d="M4 8.5h16M4 15.5h10" />
            </svg>
          </button>

          <div class="flex min-w-0 flex-1 items-center gap-2">
            <h1 class="min-w-0 truncate text-[15px] font-semibold text-fg">
              {{ work.current?.conversation.title ?? "OpenCode 工作台" }}
            </h1>
            <span
              v-if="work.current?.conversation.worktree_branch"
              class="hidden shrink-0 rounded-full bg-[color:var(--work-accent-weak)] px-2 py-0.5 font-mono text-[10.5px] font-medium sm:inline"
              style="color: var(--work-accent)"
              :title="`隔离 Git Worktree: ${work.current.conversation.workspace_path}`"
            >
              ⎇ {{ work.current.conversation.worktree_branch }}
            </span>
          </div>

          <!-- Header Actions: Command Palette / Terminal / Share / Telemetry / Status -->
          <div class="flex shrink-0 items-center gap-1.5">
            <button
              type="button"
              class="focus-ring hidden h-8 items-center gap-1.5 rounded-xl bg-surface/75 px-2.5 text-[11.5px] text-fg-faint transition-colors hover:bg-hover hover:text-fg md:inline-flex"
              title="命令与快速检索 (Ctrl+K)"
              @click="work.openCommandPalette('commands')"
            >
              <span>命令</span>
              <kbd class="font-mono text-[10px]">Ctrl+K</kbd>
            </button>

            <button
              type="button"
              class="focus-ring flex h-8 items-center gap-1 rounded-xl px-2 text-[12px] transition-colors"
              :class="work.terminalOpen ? 'bg-active font-medium text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
              title="切换集成终端 (Ctrl+`)"
              @click="work.setTerminalOpen(!work.terminalOpen)"
            >
              <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 17l6-6-6-6M12 19h8" />
              </svg>
              <span class="hidden sm:inline">终端</span>
            </button>

            <button
              v-if="work.current?.conversation.opencode_session_id"
              type="button"
              class="focus-ring hidden h-8 items-center gap-1 rounded-xl px-2 text-[12px] transition-colors sm:inline-flex"
              :class="work.current.conversation.share_url ? 'bg-accent-weak text-accent' : 'text-fg-muted hover:bg-hover hover:text-fg'"
              :title="work.current.conversation.share_url ? '点击复制分享链接' : '生成 OpenCode 分享链接'"
              @click="handleShareToggle"
            >
              <span>{{ work.current.conversation.share_url ? "已分享" : "分享" }}</span>
            </button>

            <button
              v-if="usageLabel"
              type="button"
              class="hidden whitespace-nowrap rounded-full bg-surface/80 px-2.5 py-1 text-[11px] tabular-nums text-fg-faint transition-colors hover:text-fg xl:inline"
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

        <!-- Transient Toast Notice -->
        <div
          v-if="shareNotice"
          class="mx-auto mt-2 flex w-full max-w-4xl items-center justify-between gap-3 rounded-2xl bg-surface px-4 py-2 text-[12px] text-fg"
        >
          <span class="truncate">{{ shareNotice }}</span>
          <button type="button" class="shrink-0 text-fg-faint hover:text-fg" @click="shareNotice = null">关闭</button>
        </div>

        <!-- Conversation + Bottom Overlay Area -->
        <div class="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          <WorkMessageList
            ref="messageListRef"
            :conversation-id="work.activeConversationId"
            :messages="work.messages"
            :active-assistant-id="work.activeAssistantId"
            :selected-turn-id="work.selectedTurnId"
            :streaming="work.streaming"
            :reverted-count="work.current?.reverted_count ?? 0"
            :project-name="currentProjectName"
            :bottom-inset="bottomOverlayHeight"
            @open-file="work.openFilePreview"
            @revert="handleRevert"
            @unrevert="work.unrevert()"
            @fork="handleFork"
            @steps="handleOpenSteps"
            @send-to-chat="handleSendToChat"
          />

          <div class="progressive-blur-bottom pointer-events-none absolute inset-x-0 bottom-0 z-10 h-24 sm:h-28" />
          <div class="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-transparent px-3 pb-4 pt-2 sm:px-6 sm:pb-5">
            <div class="mx-auto flex w-full max-w-4xl flex-col gap-2.5">
              <div class="pointer-events-none flex justify-center">
                <div class="pointer-events-auto">
                  <ScrollToBottomButton
                    :visible="Boolean(work.messages.length && messageListRef?.showJumpToBottom)"
                    :streaming="work.streaming"
                    :scroll-container="messageListRef?.scrollContainer ?? null"
                    @click="messageListRef?.jumpToBottom()"
                  />
                </div>
              </div>

              <div ref="bottomOverlayRef" class="pointer-events-auto w-full space-y-2.5">
                <!-- Retry Status Banner -->
                <div
                  v-if="work.retryState"
                  class="flex items-center justify-between gap-3 rounded-2xl bg-warning-weak px-3.5 py-2 text-[12.5px] text-warning"
                >
                  <span class="min-w-0 flex-1 truncate">
                    正在自动重试（第 {{ work.retryState.attempt }} 次）：{{ work.retryState.message }}
                  </span>
                  <button type="button" class="shrink-0 font-medium hover:underline" @click="work.stop()">立即停止</button>
                </div>

                <ApprovalSheet
                  v-if="work.pendingControl"
                  :kind="work.pendingControl.kind"
                  :request-id="work.pendingControl.requestId"
                  :tool="work.pendingControl.tool"
                  :preview="work.pendingControl.preview"
                  :choices="work.pendingControl.choices"
                  :patterns="work.pendingControl.patterns"
                  :always-patterns="work.pendingControl.alwaysPatterns"
                  :metadata="work.pendingControl.metadata"
                  :questions="work.pendingControl.questions"
                  :queue-count="work.pendingCount"
                  @approve="handleApprove"
                  @clarify="handleClarify"
                  @reject-clarify="handleRejectClarify"
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
        </div>

        <!-- Bottom Integrated Interactive PTY Terminal Dock -->
        <WorkTerminalDock v-if="work.terminalOpen" @close="work.setTerminalOpen(false)" />
      </div>

      <!-- Desktop Resizable Right Inspector Panel -->
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

    <!-- Command Palette (Ctrl+K / Ctrl+P / Ctrl+Shift+F) -->
    <WorkCommandPalette
      @insert-path="handleInsertPath"
      @run-command="handleCommand"
      @open-remote-sessions="openRemoteSessions()"
      @create-worktree="handleCreateWorktree()"
    />

    <!-- Full-screen Diff Review Native Modal Dialog -->
    <dialog
      ref="diffDialogRef"
      v-bind="{ closedby: 'any' }"
      aria-label="代码变更全屏评审"
      class="work-native-dialog m-auto h-[86vh] w-[min(1180px,94vw)] flex-col overflow-hidden rounded-2xl border border-line bg-canvas p-0 text-fg shadow-2xl"
      @close="onDiffDialogClose"
    >
      <div class="flex h-12 shrink-0 items-center justify-between border-b border-line px-4">
        <h2 class="text-[14px] font-semibold text-fg">代码变更评审</h2>
        <button
          type="button"
          class="rounded-lg px-2.5 py-1 text-[12px] text-fg-muted hover:bg-hover hover:text-fg"
          @click="work.diffModalOpen = false"
        >
          关闭 (Esc)
        </button>
      </div>
      <div class="flex min-h-0 flex-1 overflow-hidden">
        <div class="w-64 shrink-0 overflow-y-auto custom-scrollbar border-r border-line bg-sidebar p-2">
          <p class="px-2 py-1 text-[11px] font-medium text-fg-faint">改动文件 ({{ work.sessionDiffs.length }})</p>
          <button
            v-for="item in work.sessionDiffs"
            :key="item.file"
            type="button"
            class="flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-left text-[12px] transition-colors"
            :class="modalSelectedDiffFile === item.file ? 'bg-active font-medium text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
            @click="modalSelectedDiffFile = item.file"
          >
            <span class="truncate font-mono text-[11.5px]">{{ item.file }}</span>
            <span class="shrink-0 font-mono text-[10.5px] text-fg-faint">+{{ item.additions ?? 0 }}/-{{ item.deletions ?? 0 }}</span>
          </button>
        </div>
        <div class="flex min-w-0 flex-1 flex-col p-3">
          <WorkDiffViewer
            v-if="activeModalDiffPatch"
            :file-path="activeModalDiffPatch.file"
            :patch="activeModalDiffPatch.patch"
            :additions="activeModalDiffPatch.additions"
            :deletions="activeModalDiffPatch.deletions"
            :can-revert="work.gitStatus.is_repo"
            @close="work.diffModalOpen = false"
            @open-file="work.diffModalOpen = false; work.openFilePreview($event)"
            @open-explorer="work.openInExplorer($event)"
            @insert-path="work.diffModalOpen = false; handleInsertPath($event)"
            @revert-file="work.revertFile($event)"
          />
          <p v-else class="m-auto text-[13px] text-fg-faint">请选择左侧文件查看详细代码差异</p>
        </div>
      </div>
    </dialog>

    <!-- OpenCode CLI Remote Sessions Import Modal -->
    <BaseModal
      :open="remoteSessionsModalOpen"
      title="同步本机 OpenCode CLI 会话"
      max-width="560px"
      @close="remoteSessionsModalOpen = false"
    >
      <div class="space-y-3">
        <p class="text-[12.5px] leading-relaxed text-fg-muted">
          自动发现本机 OpenCode 守护进程在当前项目下的历史会话，导入后即可在 Whitz Work 中无缝接续对话与文件快照。
        </p>

        <div v-if="work.remoteSessionsLoading" class="py-8 text-center text-[12.5px] text-fg-faint">
          正在读取本机 OpenCode 会话列表…
        </div>
        <div v-else-if="!work.remoteSessions.length" class="rounded-xl bg-surface/65 py-8 text-center text-[12.5px] text-fg-faint">
          当前项目暂无可发现的 OpenCode 历史会话
        </div>
        <div v-else class="max-h-[50vh] space-y-2 overflow-y-auto custom-scrollbar pr-0.5">
          <div
            v-for="sess in work.remoteSessions"
            :key="sess.id"
            class="flex items-center justify-between gap-3 rounded-xl bg-surface/70 px-3.5 py-2.5"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate text-[13px] font-medium text-fg">{{ sess.title }}</p>
              <p class="mt-0.5 truncate font-mono text-[11px] text-fg-faint">
                {{ sess.id }}
                <template v-if="sess.summary && sess.summary.files">
                  · {{ sess.summary.files }} 文件 (+{{ sess.summary.additions }}/-{{ sess.summary.deletions }})
                </template>
              </p>
            </div>
            <BaseButton
              v-if="sess.linked_conversation_id"
              size="sm"
              variant="secondary"
              @click="remoteSessionsModalOpen = false; work.select(sess.linked_conversation_id!)"
            >
              打开
            </BaseButton>
            <BaseButton
              v-else
              size="sm"
              :loading="importingSessionId === sess.id"
              @click="handleImportRemote(sess.id)"
            >
              导入
            </BaseButton>
          </div>
        </div>
      </div>
    </BaseModal>
  </div>
</template>
