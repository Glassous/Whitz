<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useConversationsStore } from "../stores/conversations";
import { useChatStore } from "../stores/chat";
import { useAuthStore } from "../stores/auth";
import { useCreditsStore } from "../stores/credits";
import { useFilesStore } from "../stores/files";
import { useRealtimeStore } from "../stores/realtime";
import { api } from "../api/client";
import type { AgentStatus, ConversationFile, PreviewTarget, TaskPanelTab } from "../types";
import ConversationSidebar from "../components/chat/ConversationSidebar.vue";
import MessageList from "../components/chat/MessageList.vue";
import ChatInput from "../components/chat/ChatInput.vue";
import PlanPanel from "../components/chat/PlanPanel.vue";
import ApprovalCard from "../components/chat/ApprovalCard.vue";
import ClarifyCard from "../components/chat/ClarifyCard.vue";
import MemoryPendingCard from "../components/chat/MemoryPendingCard.vue";
import SkillPendingCard from "../components/chat/SkillPendingCard.vue";
import SearchModal from "../components/chat/SearchModal.vue";
import LibraryPanel from "../components/settings/LibraryPanel.vue";

const route = useRoute();
const router = useRouter();
const conversations = useConversationsStore();
const chat = useChatStore();
const auth = useAuthStore();
const credits = useCreditsStore();
const filesStore = useFilesStore();
const realtime = useRealtimeStore();

const sendingMessage = ref(false);
const deletingFileId = ref<string | null>(null);
const downloadingFileId = ref<string | null>(null);
let openSeq = 0;

const routeConversationId = computed(() => (typeof route.params.id === "string" && route.params.id ? route.params.id : null));
const isNewSideDraft = computed(() => route.query.new === "1");

const activeView = ref<"chat" | "library">("chat");

const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
const assistantAvatarUrl = computed(() => auth.user?.assistant_avatar_url ?? null);
const isMainChat = computed(() => conversations.current?.kind === "main");
const headerTitle = computed(() => {
  if (activeView.value === "library") return "资料库";
  if (isMainChat.value) return "主要聊天";
  return conversations.current?.title ?? "新旁聊";
});

const PANEL_WIDTH_STORAGE_KEY = "whitz_task_panel_width";
const DEFAULT_PANEL_WIDTH = 340;
const MIN_PANEL_WIDTH = 300;
const PREVIEW_MIN_PANEL_WIDTH = 500;

function maxPanelWidth(): number {
  if (typeof window === "undefined") return 820;
  return Math.max(MIN_PANEL_WIDTH, Math.floor(Math.min(820, window.innerWidth * 0.62)));
}

function clampPanelWidth(w: number): number {
  return Math.round(Math.max(MIN_PANEL_WIDTH, Math.min(maxPanelWidth(), w)));
}

function loadInitialPanelWidth(): number {
  if (typeof window === "undefined") return DEFAULT_PANEL_WIDTH;
  try {
    const raw = window.localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
    if (!raw) return clampPanelWidth(DEFAULT_PANEL_WIDTH);
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? clampPanelWidth(parsed) : clampPanelWidth(DEFAULT_PANEL_WIDTH);
  } catch {
    return DEFAULT_PANEL_WIDTH;
  }
}

function savePanelWidth(width: number) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(width));
  } catch {
    /* ignore storage failures */
  }
}

const agent = ref<AgentStatus | null>(null);
const showPlan = ref(false);
const planTab = ref<TaskPanelTab>("steps");
const previewTarget = ref<PreviewTarget | null>(null);
const panelWidth = ref<number>(loadInitialPanelWidth());
const isResizingPanel = ref(false);
let prePreviewPanelWidth: number | null = null;
let resizeStartX = 0;
let resizeStartWidth = DEFAULT_PANEL_WIDTH;

const selectedSkills = ref<string[]>([]);
const pendingBusyIds = ref<Set<string>>(new Set());
const pendingErrors = ref<Record<string, string>>({});

const SIDEBAR_COLLAPSED_KEY = "whitz_sidebar_collapsed";
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(
  typeof window !== "undefined" ? window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1" : false,
);
const drawerDragProgress = ref<number | null>(null);
const mobileStepsOpen = ref(false);
const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;
function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
  if (e.matches) sidebarOpen.value = false;
}
function onWindowResize() {
  panelWidth.value = clampPanelWidth(panelWidth.value);
}
const searchOpen = ref(false);
const focusMessageId = ref<string | null>(null);
let pollTimer: number | null = null;

function onPanelResizePointerDown(e: PointerEvent) {
  if (!showPlan.value) return;
  const target = e.currentTarget as HTMLElement;
  target.setPointerCapture(e.pointerId);
  isResizingPanel.value = true;
  resizeStartX = e.clientX;
  resizeStartWidth = panelWidth.value;
  prePreviewPanelWidth = null;
}

function onPanelResizePointerMove(e: PointerEvent) {
  if (!isResizingPanel.value) return;
  const delta = resizeStartX - e.clientX;
  panelWidth.value = clampPanelWidth(resizeStartWidth + delta);
}

function onPanelResizePointerUp(e: PointerEvent) {
  if (!isResizingPanel.value) return;
  isResizingPanel.value = false;
  const target = e.currentTarget as HTMLElement;
  if (target.hasPointerCapture(e.pointerId)) {
    target.releasePointerCapture(e.pointerId);
  }
  savePanelWidth(panelWidth.value);
}

function onPanelResizeKeydown(e: KeyboardEvent) {
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    prePreviewPanelWidth = null;
    panelWidth.value = clampPanelWidth(panelWidth.value + 24);
    savePanelWidth(panelWidth.value);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    prePreviewPanelWidth = null;
    panelWidth.value = clampPanelWidth(panelWidth.value - 24);
    savePanelWidth(panelWidth.value);
  }
}

function setSidebarCollapsed(next: boolean) {
  sidebarCollapsed.value = next;
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function toggleSidebarCollapsed() {
  setSidebarCollapsed(!sidebarCollapsed.value);
}

function onPlanToggleClick() {
  if (window.innerWidth >= 1024) {
    showPlan.value = !showPlan.value;
  } else {
    mobileStepsOpen.value = true;
  }
}

function onSidebarToggleClick() {
  if (window.innerWidth >= 768) {
    toggleSidebarCollapsed();
  } else {
    sidebarOpen.value = true;
  }
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
    e.preventDefault();
    if (window.innerWidth >= 768) {
      toggleSidebarCollapsed();
    } else {
      sidebarOpen.value = !sidebarOpen.value;
    }
  } else if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
    e.preventDefault();
    searchOpen.value = !searchOpen.value;
  }
}

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 5) return "夜深了";
  if (h < 12) return "早上好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});

const userName = computed(() => auth.user?.display_name?.trim() ?? "");

async function loadAgent() {
  try {
    agent.value = await api.get<AgentStatus>("/agent/status");
  } catch {
    agent.value = { ready: false, status: "error" };
  }
  if (agent.value && !agent.value.ready && agent.value.status === "warming_up") {
    pollTimer = window.setTimeout(loadAgent, 5000);
  }
}

async function openConversation(id: string): Promise<boolean> {
  const seq = ++openSeq;
  try {
    const detail = await conversations.open(id);
    if (seq !== openSeq) return false;
    chat.loadFromConversation(detail);
    if (detail.kind !== "main") {
      void filesStore.load(id);
    } else {
      filesStore.reset();
      filesStore.convId = id;
    }
    return true;
  } catch {
    if (seq !== openSeq) return false;
    conversations.clearCurrent();
    chat.reset();
    filesStore.reset();
    return false;
  }
}

async function openMainConversation() {
  activeView.value = "chat";
  sidebarOpen.value = false;
  mobileStepsOpen.value = false;
  focusMessageId.value = null;
  const mainId = conversations.mainConversation?.id;
  if (mainId && mainId === conversations.current?.id) {
    if (routeConversationId.value !== mainId) {
      void router.replace({ name: "chat-conversation", params: { id: mainId } });
    }
    return;
  }
  chat.abort();
  previewTarget.value = null;
  selectedSkills.value = [];
  try {
    const detail = mainId ? await conversations.open(mainId) : await conversations.openMain();
    chat.loadFromConversation(detail);
    filesStore.reset();
    filesStore.convId = detail.id;
    showPlan.value = true;
    planTab.value = "steps";
    if (routeConversationId.value !== detail.id) {
      void router.replace({ name: "chat-conversation", params: { id: detail.id } });
    }
  } catch {
    /* ignore */
  }
}

function createSideConversation() {
  activeView.value = "chat";
  chat.abort();
  conversations.clearCurrent();
  chat.reset();
  filesStore.reset();
  previewTarget.value = null;
  selectedSkills.value = [];
  showPlan.value = false;
  planTab.value = "steps";
  void router.push({ name: "chat", query: { new: "1" } });
}

function onSwitchView(view: "chat" | "library") {
  activeView.value = view;
  if (view === "library") {
    previewTarget.value = null;
    mobileStepsOpen.value = false;
  } else if (!conversations.current && !isNewSideDraft.value) {
    void openMainConversation();
  }
}

async function onSelect(id: string) {
  activeView.value = "chat";
  sidebarOpen.value = false;
  mobileStepsOpen.value = false;
  focusMessageId.value = null;
  if (id === conversations.current?.id) {
    if (routeConversationId.value !== id) {
      void router.push({ name: "chat-conversation", params: { id } });
    }
    return;
  }
  chat.abort();
  previewTarget.value = null;
  selectedSkills.value = [];
  const ok = await openConversation(id);
  if (ok) {
    showPlan.value = true;
    if (routeConversationId.value !== id) {
      void router.push({ name: "chat-conversation", params: { id } });
    }
  }
}

async function onSelectFromSearch(conversationId: string, messageId: string | null) {
  activeView.value = "chat";
  sidebarOpen.value = false;
  mobileStepsOpen.value = false;
  if (conversationId !== conversations.current?.id) {
    chat.abort();
    previewTarget.value = null;
    selectedSkills.value = [];
    const ok = await openConversation(conversationId);
    if (!ok) return;
  }
  if (routeConversationId.value !== conversationId) {
    void router.push({ name: "chat-conversation", params: { id: conversationId } });
  }
  showPlan.value = true;
  focusMessageId.value = messageId;
}

async function onRename(id: string, title: string) {
  await conversations.rename(id, title);
}

async function onPin(id: string, isPinned: boolean) {
  await conversations.togglePin(id, isPinned);
}

async function onDelete(id: string) {
  const wasCurrent = conversations.current?.id === id;
  await conversations.remove(id);
  if (wasCurrent) {
    chat.reset();
    previewTarget.value = null;
    selectedSkills.value = [];
    const fallback = conversations.sideConversations[0] ?? conversations.mainConversation;
    if (fallback) {
      const ok = await openConversation(fallback.id);
      if (ok) {
        showPlan.value = true;
        void router.replace({ name: "chat-conversation", params: { id: fallback.id } });
      } else {
        void openMainConversation();
      }
    } else {
      void openMainConversation();
    }
  }
}

async function ensureConversationId(): Promise<string> {
  if (conversations.current?.id) return conversations.current.id;
  const conv = await conversations.create("新旁聊");
  await openConversation(conv.id);
  void router.replace({ name: "chat-conversation", params: { id: conv.id } });
  return conv.id;
}

async function onUploadFiles(fileList: FileList, dataTransfer?: DataTransfer | null, switchToFilesTab = false) {
  if (!agent.value?.ready) return;
  if (switchToFilesTab && !isMainChat.value) {
    previewTarget.value = null;
    showPlan.value = true;
    planTab.value = "files";
  }
  const started = await filesStore.enqueueFiles(fileList, ensureConversationId, dataTransfer);
  if (started && !isMainChat.value && window.innerWidth >= 1024) {
    showPlan.value = true;
  }
}

function onRetryUpload(localId: string) {
  if (!agent.value?.ready) return;
  void filesStore.retryUpload(localId, ensureConversationId);
}

async function onAttachLibraryFiles(fileIds: string[]) {
  if (!agent.value?.ready || !fileIds.length) return;
  try {
    const cid = await ensureConversationId();
    await filesStore.attachLibraryFiles(fileIds, cid, true);
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "引用资料库文件失败";
    throw e;
  }
}

async function onDeleteFile(fileId: string) {
  if (deletingFileId.value === fileId) return;
  deletingFileId.value = fileId;
  try {
    await filesStore.removeFile(fileId);
    if (previewTarget.value?.kind === "file" && previewTarget.value.file.id === fileId) {
      previewTarget.value = null;
    }
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "删除文件失败";
  } finally {
    if (deletingFileId.value === fileId) deletingFileId.value = null;
  }
}

async function onDownloadFile(file: ConversationFile) {
  if (downloadingFileId.value === file.id) return;
  downloadingFileId.value = file.id;
  try {
    const url = await filesStore.getDownloadUrl(file.id, false, file.conversation_id ?? undefined);
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "获取下载链接失败";
  } finally {
    if (downloadingFileId.value === file.id) downloadingFileId.value = null;
  }
}

function openPreviewTarget(next: PreviewTarget) {
  previewTarget.value = next;
  if (window.innerWidth >= 1024) {
    showPlan.value = true;
  } else {
    mobileStepsOpen.value = true;
  }
}

function onPreviewFile(file: ConversationFile) {
  openPreviewTarget({ kind: "file", file });
}

function onPreviewHtml(html: string) {
  openPreviewTarget({ kind: "html", html, title: "HTML 代码预览" });
}

function closePreview() {
  previewTarget.value = null;
}

function closeMobileDrawer() {
  mobileStepsOpen.value = false;
  previewTarget.value = null;
}

async function onSend(content: string) {
  if (sendingMessage.value || chat.streaming || filesStore.hasActiveUploads) return;
  sendingMessage.value = true;
  try {
    await ensureConversationId();
    const attached = filesStore.attachedFiles;
    filesStore.consumeAttachedIds();
    const skillNames = [...selectedSkills.value];
    selectedSkills.value = [];
    planTab.value = "steps";
    const sendPromise = chat.send(content, attached, skillNames);
    sendingMessage.value = false;
    await sendPromise;
    await conversations.fetchList();
  } catch (e: any) {
    chat.error = e?.detail?.detail ?? e?.message ?? "无法开始对话，请稍后重试";
  } finally {
    sendingMessage.value = false;
  }
}

async function onRegenerate(assistantMessageId: string) {
  if (chat.streaming || filesStore.hasActiveUploads) return;
  try {
    await chat.regenerate(assistantMessageId);
    await conversations.fetchList();
  } catch (e: any) {
    chat.error = e?.detail?.detail ?? e?.message ?? "重新生成失败，请稍后重试";
  }
}

async function onEditMessage(userMessageId: string, content: string) {
  if (chat.streaming || filesStore.hasActiveUploads) return;
  try {
    const original = chat.messages.find((m) => m.id === userMessageId && m.role === "user");
    const existingAttachments = original?.tool_payload?.attachments ?? [];
    const resolvedAttached: ConversationFile[] = existingAttachments.map((att) => {
      const found = filesStore.files.find((f) => f.id === att.id);
      if (found) return found;
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
        created_at: original?.created_at ?? new Date().toISOString(),
        updated_at: original?.created_at ?? new Date().toISOString(),
      };
    });
    const existingSkills = original?.tool_payload?.skills ?? [];
    await chat.editAndResend(userMessageId, content, resolvedAttached, existingSkills);
    await conversations.fetchList();
  } catch (e: any) {
    chat.error = e?.detail?.detail ?? e?.message ?? "保存并重发失败，请稍后重试";
  }
}

async function onResolveMemory(id: string, action: "approve" | "reject", content?: string) {
  const nextBusy = new Set(pendingBusyIds.value);
  nextBusy.add(id);
  pendingBusyIds.value = nextBusy;
  const { [id]: _, ...restErrors } = pendingErrors.value;
  pendingErrors.value = restErrors;
  try {
    await chat.resolvePendingMemory(id, action, content);
  } catch (e: any) {
    pendingErrors.value = {
      ...pendingErrors.value,
      [id]: e?.detail?.detail ?? e?.message ?? "操作失败，请重试",
    };
  } finally {
    const afterBusy = new Set(pendingBusyIds.value);
    afterBusy.delete(id);
    pendingBusyIds.value = afterBusy;
  }
}

async function onResolveSkill(id: string, action: "approve" | "reject") {
  const nextBusy = new Set(pendingBusyIds.value);
  nextBusy.add(id);
  pendingBusyIds.value = nextBusy;
  const { [id]: _, ...restErrors } = pendingErrors.value;
  pendingErrors.value = restErrors;
  try {
    await chat.resolvePendingSkill(id, action);
  } catch (e: any) {
    pendingErrors.value = {
      ...pendingErrors.value,
      [id]: e?.detail?.detail ?? e?.message ?? "操作失败，请重试",
    };
  } finally {
    const afterBusy = new Set(pendingBusyIds.value);
    afterBusy.delete(id);
    pendingBusyIds.value = afterBusy;
  }
}

function onViewSteps(id: string) {
  chat.selectTurn(id);
  previewTarget.value = null;
  planTab.value = "steps";
  showPlan.value = true;
  if (window.innerWidth < 1024) mobileStepsOpen.value = true;
}

watch(previewTarget, (next, prev) => {
  if (next && !prev) {
    if (panelWidth.value < PREVIEW_MIN_PANEL_WIDTH) {
      prePreviewPanelWidth = panelWidth.value;
      panelWidth.value = clampPanelWidth(PREVIEW_MIN_PANEL_WIDTH);
    }
  } else if (!next && prev) {
    if (prePreviewPanelWidth !== null) {
      panelWidth.value = clampPanelWidth(prePreviewPanelWidth);
      prePreviewPanelWidth = null;
    }
  }
});

watch(
  () => chat.streaming,
  (val, old) => {
    if (val && !old) {
      showPlan.value = true;
    }
    if (old && !val) {
      void conversations.fetchList();
      void credits.fetch();
    }
  },
);

watch([routeConversationId, isNewSideDraft], async ([nextId, draft]) => {
  if (nextId) {
    activeView.value = "chat";
    if (nextId !== conversations.current?.id) {
      chat.abort();
      previewTarget.value = null;
      selectedSkills.value = [];
      const ok = await openConversation(nextId);
      if (ok) {
        showPlan.value = true;
      } else {
        showPlan.value = false;
        void openMainConversation();
      }
    }
  } else if (draft) {
    activeView.value = "chat";
    if (conversations.current) {
      chat.abort();
      conversations.clearCurrent();
      chat.reset();
      filesStore.reset();
      previewTarget.value = null;
      selectedSkills.value = [];
      showPlan.value = false;
    }
  } else if (!conversations.current && conversations.mainConversation) {
    void openMainConversation();
  }
});

function onOnlineRecovery() {
  void chat.recoverIfNeeded();
}

function onVisibilityRecovery() {
  if (typeof document !== "undefined" && document.visibilityState === "visible") {
    void chat.recoverIfNeeded();
  }
}

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKeydown);
  window.addEventListener("resize", onWindowResize);
  window.addEventListener("online", onOnlineRecovery);
  document.addEventListener("visibilitychange", onVisibilityRecovery);
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  realtime.start();
  void loadAgent();
  void credits.fetch();
  await conversations.fetchList();
  if (routeConversationId.value) {
    const ok = await openConversation(routeConversationId.value);
    if (ok) {
      showPlan.value = true;
    } else {
      await openMainConversation();
    }
  } else if (isNewSideDraft.value) {
    conversations.clearCurrent();
    chat.reset();
  } else {
    await openMainConversation();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  window.removeEventListener("resize", onWindowResize);
  window.removeEventListener("online", onOnlineRecovery);
  document.removeEventListener("visibilitychange", onVisibilityRecovery);
  mediaQuery?.removeEventListener("change", onMediaChange);
  if (pollTimer) window.clearTimeout(pollTimer);
  realtime.stop();
  chat.abort();
});
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-canvas">
    <Transition
      enter-active-class="transition duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]"
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

    <ConversationSidebar
      :main-conversation="conversations.mainConversation"
      :side-conversations="conversations.sideConversations"
      :current-id="conversations.current?.id ?? null"
      :active-view="activeView"
      :loading="conversations.loading"
      :open="sidebarOpen"
      :collapsed="sidebarCollapsed"
      :rename-action="onRename"
      :delete-action="onDelete"
      @select="onSelect"
      @select-main="openMainConversation"
      @create-side="createSideConversation"
      @switch-view="onSwitchView"
      @toggle-collapse="toggleSidebarCollapsed"
      @rename="onRename"
      @pin="onPin"
      @delete="onDelete"
      @close="sidebarOpen = false"
      @open-search="searchOpen = true"
      @drag-progress="drawerDragProgress = $event"
    />

    <main class="relative flex min-w-0 flex-1" :inert="(!isDesktop && sidebarOpen) || undefined">
      <!-- Embedded Library View inside Homepage Main Area -->
      <template v-if="activeView === 'library'">
        <div class="relative flex min-w-0 flex-1 flex-col">
          <div class="flex shrink-0 items-center gap-2.5 border-b border-line/60 px-3.5 py-3">
            <button
              type="button"
              class="focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
              :aria-label="sidebarCollapsed ? '展开侧栏' : '切换侧栏'"
              :title="sidebarCollapsed ? '展开侧栏 (Ctrl+B)' : '收起侧栏 (Ctrl+B)'"
              @click="onSidebarToggleClick"
            >
              <svg class="h-[22px] w-[22px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3">
                <path stroke-linecap="round" d="M4 8.5h16M4 15.5h10" />
              </svg>
            </button>
            <h1 class="min-w-0 truncate text-[16px] font-semibold text-fg">资料库</h1>
          </div>
          <div v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8">
            <div class="mx-auto w-full max-w-6xl">
              <LibraryPanel embedded />
            </div>
          </div>
        </div>
      </template>

      <!-- Chat Workspace View (Main Chat & Side Chats) -->
      <template v-else>
      <!-- Fixed task panel toggle (top-right inside panel when expanded, same position when collapsed) -->
      <button
        type="button"
        class="focus-ring absolute right-3.5 top-3.5 z-30 inline-flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
        :aria-label="showPlan ? '收起右侧栏' : '展开右侧栏'"
        :title="showPlan ? '收起右侧栏' : '展开右侧栏'"
        @click="onPlanToggleClick"
      >
        <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 5h18v14H3zM15 5v14" />
        </svg>
        <span
          v-if="!isMainChat && filesStore.fileCount > 0 && !showPlan"
          class="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-accent"
          aria-hidden="true"
        />
      </button>

      <div class="relative flex min-w-0 flex-1 flex-col">
        <!-- Progressive blur top zone + floating sidebar toggle & conversation title -->
        <div class="progressive-blur-top pointer-events-none absolute inset-x-0 top-0 z-20 h-20" />
        <div
          class="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-center gap-2.5 px-3.5 pt-3.5"
          :class="showPlan ? 'pr-16 lg:pr-4' : 'pr-16'"
        >
          <button
            type="button"
            class="focus-ring pointer-events-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
            :aria-label="sidebarCollapsed ? '展开侧栏' : '切换侧栏'"
            :title="sidebarCollapsed ? '展开侧栏 (Ctrl+B)' : '收起侧栏 (Ctrl+B)'"
            @click="onSidebarToggleClick"
          >
            <svg class="h-[22px] w-[22px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3">
              <path stroke-linecap="round" d="M4 8.5h16M4 15.5h10" />
            </svg>
          </button>

          <h1 class="min-w-0 truncate text-[15.5px] font-semibold text-fg">
            {{ headerTitle }}
          </h1>
        </div>

        <div class="relative min-h-0 flex-1">
          <MessageList
            v-if="chat.messages.length"
            :key="chat.convId ?? 'draft'"
            :messages="chat.messages"
            :focus-message-id="focusMessageId"
            :downloading-file-id="downloadingFileId"
            @steps="onViewSteps"
            @focus-handled="focusMessageId = null"
            @regenerate="onRegenerate"
            @edit="onEditMessage"
            @preview-html="onPreviewHtml"
            @preview-file="onPreviewFile"
            @download-file="onDownloadFile"
          />

          <div v-else v-scrollbar class="custom-scrollbar h-full overflow-y-auto">
            <div class="flex min-h-full flex-col items-center justify-center px-4 pb-32 pt-32 sm:px-6 sm:pt-40">
              <div class="w-full max-w-2xl text-center">
                <h1 class="text-[32px] font-semibold leading-10 tracking-tight text-fg sm:text-[38px] sm:leading-[44px]">
                  {{ greeting }}<template v-if="userName">，{{ userName }}</template>
                </h1>
                <p class="mx-auto mt-3.5 max-w-lg text-[16px] text-fg-muted sm:text-[17px]">
                  <template v-if="isMainChat">
                    我是你的专属助手 {{ assistantName }}，随时关联你的所有旁聊与资料库。今天想做点什么？
                  </template>
                  <template v-else>
                    新建旁聊专注讨论单个主题；发送的文件会自动沉淀到全局资料库。
                  </template>
                </p>

                <p
                  class="mt-5 h-4 text-[13.5px] text-fg-faint transition-opacity duration-200"
                  :class="agent && !agent.ready ? 'opacity-100' : 'pointer-events-none opacity-0'"
                >
                  助理正在初始化，稍后即可开始对话…
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="progressive-blur-bottom pointer-events-none absolute inset-x-0 bottom-0 z-10 h-24 sm:h-28" />
        <div class="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-transparent px-3 pb-4 pt-2 sm:px-6 sm:pb-5">
          <div class="pointer-events-auto mx-auto w-full max-w-4xl space-y-3">
            <Transition
              mode="out-in"
              enter-active-class="transition duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]"
              enter-from-class="translate-y-2 opacity-0"
              enter-to-class="translate-y-0 opacity-100"
              leave-active-class="transition duration-150 ease-in"
              leave-from-class="translate-y-0 opacity-100"
              leave-to-class="translate-y-2 opacity-0"
            >
              <ApprovalCard
                v-if="chat.pendingControl?.kind === 'approval'"
                :control="chat.pendingControl"
                :submitting-choice="chat.approvingChoice"
                @decide="chat.approve"
              />
              <ClarifyCard
                v-else-if="chat.pendingControl?.kind === 'clarify'"
                :control="chat.pendingControl"
                :submitting="chat.submittingClarify"
                @submit="chat.clarify"
              />
            </Transition>

            <MemoryPendingCard
              v-for="item in chat.pendingMemory"
              :key="`mem-${item.id}`"
              :item="item"
              :busy="pendingBusyIds.has(item.id)"
              :error="pendingErrors[item.id] ?? null"
              @resolve="onResolveMemory"
            />

            <SkillPendingCard
              v-for="item in chat.pendingSkills"
              :key="`skill-${item.id}`"
              :item="item"
              :busy="pendingBusyIds.has(item.id)"
              :error="pendingErrors[item.id] ?? null"
              @resolve="onResolveSkill"
            />

            <Transition
              enter-active-class="transition duration-200 ease-out"
              enter-from-class="-translate-y-1 opacity-0"
              enter-to-class="translate-y-0 opacity-100"
              leave-active-class="transition duration-150 ease-in"
              leave-from-class="translate-y-0 opacity-100"
              leave-to-class="-translate-y-1 opacity-0"
            >
              <div v-if="filesStore.error" class="flex items-start gap-2 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">
                <span class="flex-1">{{ filesStore.error }}</span>
                <button class="rounded p-0.5 transition-opacity hover:opacity-70" aria-label="关闭文件提示" @click="filesStore.clearError()">
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </div>
            </Transition>

            <Transition
              enter-active-class="transition duration-200 ease-out"
              enter-from-class="-translate-y-1 opacity-0"
              enter-to-class="translate-y-0 opacity-100"
              leave-active-class="transition duration-150 ease-in"
              leave-from-class="translate-y-0 opacity-100"
              leave-to-class="-translate-y-1 opacity-0"
            >
              <div v-if="chat.error" class="flex items-start gap-2 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">
                <span class="flex-1">{{ chat.error }}</span>
                <router-link
                  v-if="chat.error.includes('积分')"
                  to="/settings"
                  class="shrink-0 rounded-md bg-canvas px-2 py-0.5 text-[12px] font-medium text-accent transition-opacity hover:opacity-70"
                >
                  查看会员
                </router-link>
                <button class="rounded p-0.5 transition-opacity hover:opacity-70" aria-label="关闭提示" @click="chat.error = null">
                  <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </div>
            </Transition>

            <ChatInput
              v-model:selected-skills="selectedSkills"
              :streaming="chat.streaming"
              :sending="sendingMessage || chat.waitingFirstByte"
              :stopping="chat.stopping"
              :disabled="!agent?.ready"
              :uploading="filesStore.hasActiveUploads"
              :uploads="filesStore.uploads"
              :attached-files="filesStore.attachedFiles"
              :assistant-name="assistantName"
              @send="onSend"
              @stop="chat.stop"
              @upload="(files, dt) => onUploadFiles(files, dt, false)"
              @cancel-upload="filesStore.cancelUpload"
              @dismiss-upload="filesStore.dismissUpload"
              @retry-upload="onRetryUpload"
              @detach-file="filesStore.detachFile"
            />
          </div>
        </div>
      </div>

      <aside
        class="relative hidden h-full shrink-0 overflow-hidden bg-sidebar lg:block"
        :class="[
          showPlan ? 'opacity-100' : 'pointer-events-none opacity-0',
          isResizingPanel ? 'transition-none' : 'transition-[width,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]',
        ]"
        :style="{ width: showPlan ? `${panelWidth}px` : '0px' }"
        :aria-hidden="!showPlan"
      >
        <div
          v-if="showPlan"
          role="separator"
          tabindex="0"
          aria-orientation="vertical"
          aria-label="调整任务面板宽度"
          :aria-valuemin="MIN_PANEL_WIDTH"
          :aria-valuemax="maxPanelWidth()"
          :aria-valuenow="panelWidth"
          title="左右拖拽调整面板宽度"
          class="focus-ring group absolute inset-y-0 left-0 z-30 flex w-2.5 cursor-col-resize touch-none select-none items-center justify-center transition-colors hover:bg-hover/60"
          :class="isResizingPanel ? 'bg-hover/80' : ''"
          @pointerdown="onPanelResizePointerDown"
          @pointermove="onPanelResizePointerMove"
          @pointerup="onPanelResizePointerUp"
          @pointercancel="onPanelResizePointerUp"
          @keydown="onPanelResizeKeydown"
        >
          <span
            class="h-10 w-0.5 rounded-full transition-colors"
            :class="isResizingPanel ? 'bg-accent' : 'bg-transparent group-hover:bg-line-strong'"
            aria-hidden="true"
          />
        </div>
        <div class="h-full" :style="{ width: `${panelWidth}px` }">
          <PlanPanel
            v-model:active-tab="planTab"
            :mode="isMainChat ? 'main' : 'side'"
            :assistant-name="assistantName"
            :assistant-avatar-url="assistantAvatarUrl"
            :plan="chat.viewPlan"
            :reasoning="chat.viewReasoning"
            :streaming="chat.viewStreaming"
            :current-step="chat.viewCurrentStep"
            :running-tool="chat.viewRunningTool"
            :turn-key="chat.selectedTurn?.id ?? ''"
            :files="filesStore.files"
            :uploads="filesStore.uploads"
            :files-loading="filesStore.loading"
            :upload-disabled="!agent?.ready"
            :preview-target="previewTarget"
            :resizing="isResizingPanel"
            :deleting-file-id="deletingFileId"
            :downloading-file-id="downloadingFileId"
            :attach-library-action="onAttachLibraryFiles"
            @upload="(files, dt) => onUploadFiles(files, dt, true)"
            @cancel-upload="filesStore.cancelUpload"
            @dismiss-upload="filesStore.dismissUpload"
            @retry-upload="onRetryUpload"
            @delete-file="onDeleteFile"
            @download-file="onDownloadFile"
            @preview-file="onPreviewFile"
            @close-preview="closePreview"
            @attach-library="onAttachLibraryFiles"
          />
        </div>
      </aside>
      </template>
    </main>

    <Transition
      enter-active-class="transition duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]"
      enter-from-class="opacity-0 [&>div:last-child]:translate-x-full"
      enter-to-class="opacity-100 [&>div:last-child]:translate-x-0"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100 [&>div:last-child]:translate-x-0"
      leave-to-class="opacity-0 [&>div:last-child]:translate-x-full"
    >
      <div v-if="mobileStepsOpen && activeView === 'chat'" class="fixed inset-0 z-40 lg:hidden">
        <div class="absolute inset-0 bg-black/40" @click="closeMobileDrawer" />
        <div
          class="absolute inset-y-0 right-0 flex flex-col bg-sidebar shadow-2xl transition-[width,transform] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]"
          :class="previewTarget ? 'w-full max-w-[100dvw] overflow-x-hidden' : 'w-[min(360px,90dvw)]'"
        >
          <div class="flex h-13 shrink-0 items-center justify-between pl-4 pr-2.5">
            <h3 class="text-[16px] font-semibold text-fg">{{ isMainChat ? "助手与步骤" : "任务面板" }}</h3>
            <button
              type="button"
              class="focus-ring flex h-9 w-9 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              aria-label="关闭任务面板"
              @click="closeMobileDrawer"
            >
              <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div class="min-h-0 flex-1">
            <PlanPanel
              v-model:active-tab="planTab"
              :hide-header="true"
              :mode="isMainChat ? 'main' : 'side'"
              :assistant-name="assistantName"
              :assistant-avatar-url="assistantAvatarUrl"
              :plan="chat.viewPlan"
              :reasoning="chat.viewReasoning"
              :streaming="chat.viewStreaming"
              :current-step="chat.viewCurrentStep"
              :running-tool="chat.viewRunningTool"
              :turn-key="chat.selectedTurn?.id ?? ''"
              :files="filesStore.files"
              :uploads="filesStore.uploads"
              :files-loading="filesStore.loading"
              :upload-disabled="!agent?.ready"
              :preview-target="previewTarget"
              :deleting-file-id="deletingFileId"
              :downloading-file-id="downloadingFileId"
              :attach-library-action="onAttachLibraryFiles"
              @upload="(files, dt) => onUploadFiles(files, dt, true)"
              @cancel-upload="filesStore.cancelUpload"
              @dismiss-upload="filesStore.dismissUpload"
              @retry-upload="onRetryUpload"
              @delete-file="onDeleteFile"
              @download-file="onDownloadFile"
              @preview-file="onPreviewFile"
              @close-preview="closePreview"
              @attach-library="onAttachLibraryFiles"
            />
          </div>
        </div>
      </div>
    </Transition>
    <SearchModal
      :open="searchOpen"
      :conversations="conversations.conversations"
      @close="searchOpen = false"
      @select="onSelectFromSearch"
    />
  </div>
</template>
