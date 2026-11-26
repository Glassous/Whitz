<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { APP_SHELL_KEY } from "../layouts/AppShellLayout.vue";
import { useConversationsStore } from "../stores/conversations";
import { useChatStore } from "../stores/chat";
import { useAuthStore } from "../stores/auth";
import { useCreditsStore } from "../stores/credits";
import { useFilesStore } from "../stores/files";
import { useRealtimeStore } from "../stores/realtime";
import { api } from "../api/client";
import { extractFileIdsFromText } from "../lib/fileTokens";
import type { AgentStatus, CitationItem, ConversationFile, DeliverableTarget, PreviewTarget, TaskPanelTab } from "../types";
import ConversationSidebar from "../components/chat/ConversationSidebar.vue";
import MessageList from "../components/chat/MessageList.vue";
import ScrollToBottomButton from "../components/ui/ScrollToBottomButton.vue";
import AppIcon from "../components/ui/AppIcon.vue";
import ChatInput from "../components/chat/ChatInput.vue";
import PlanPanel from "../components/chat/PlanPanel.vue";
import ApprovalCard from "../components/chat/ApprovalCard.vue";
import ClarifyCard from "../components/chat/ClarifyCard.vue";
import MemoryPendingCard from "../components/chat/MemoryPendingCard.vue";
import SkillPendingCard from "../components/chat/SkillPendingCard.vue";
import SchedulePendingCard from "../components/chat/SchedulePendingCard.vue";
import SearchModal from "../components/chat/SearchModal.vue";
import ContextStateModal from "../components/chat/ContextStateModal.vue";
import DeliverableModal from "../components/chat/DeliverableModal.vue";
import ImageLightboxModal from "../components/chat/ImageLightboxModal.vue";

const route = useRoute();
const router = useRouter();
const shell = inject(APP_SHELL_KEY, null);
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

const activeView = ref<"chat">("chat");

const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
const assistantAvatarUrl = computed(() => auth.user?.assistant_avatar_url ?? null);
const isMainChat = computed(() => conversations.current?.kind === "main");
const isCurrentScheduled = computed(() => {
  const cur = conversations.current;
  if (!cur || cur.kind === "main") return false;
  return Boolean(cur.is_scheduled || (cur.title || "").startsWith("[定时]"));
});
const headerTitle = computed(() => {
  if (isMainChat.value) return "主要聊天";
  const raw = conversations.current?.title ?? "新旁聊";
  if (isCurrentScheduled.value) {
    return raw.replace(/^\[定时\]\s*/, "").trim() || raw;
  }
  return raw;
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
const mainFileScope = ref<"all" | "conversation">("all");
const previewTarget = ref<PreviewTarget | null>(null);
const deliverableTarget = ref<DeliverableTarget | null>(null);
const lightboxOpen = ref(false);
const lightboxImages = ref<ConversationFile[]>([]);
const lightboxIndex = ref(0);
const chatInputRef = ref<InstanceType<typeof ChatInput> | null>(null);
const messageListRef = ref<InstanceType<typeof MessageList> | null>(null);
const bottomOverlayRef = ref<HTMLElement | null>(null);
const bottomOverlayHeight = ref(0);
let bottomOverlayObserver: ResizeObserver | null = null;
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
const contextStateOpen = ref(false);
const focusMessageId = ref<string | null>(null);
let pollTimer: number | null = null;
let agentRetryBackoffMs = 5000;

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
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  try {
    agent.value = await api.get<AgentStatus>("/agent/status");
    if (agent.value?.ready) {
      agentRetryBackoffMs = 5000;
      return;
    }
  } catch {
    agent.value = { ready: false, status: "error" };
  }
  if (agent.value && !agent.value.ready) {
    const delay = agent.value.status === "warming_up" ? 5000 : agentRetryBackoffMs;
    agentRetryBackoffMs = Math.min(agentRetryBackoffMs + 5000, 15000);
    pollTimer = window.setTimeout(loadAgent, delay);
  }
}

async function openConversation(id: string): Promise<boolean> {
  const seq = ++openSeq;
  try {
    const detail = await conversations.open(id);
    if (seq !== openSeq) return false;
    chat.loadFromConversation(detail);
    void filesStore.load(id, detail.kind === "main" ? mainFileScope.value : "conversation");
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
    void filesStore.load(detail.id, mainFileScope.value);
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

function onSwitchView(view: "chat" | "posts" | "library" | "schedules") {
  if (view === "posts") {
    void router.push({ name: "posts" });
    return;
  }
  if (view === "library") {
    void router.push({ name: "library" });
    return;
  }
  if (view === "schedules") {
    void router.push({ name: "schedules" });
    return;
  }
  if (!conversations.current && !isNewSideDraft.value) {
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

function buildSyntheticFile(fileId: string, filename: string, conversationId: string | null): ConversationFile {
  const existing = filesStore.files.find((f) => f.id === fileId);
  if (existing) return existing;
  const dotIdx = filename.lastIndexOf(".");
  const ext = dotIdx >= 0 ? filename.slice(dotIdx).toLowerCase() : "";
  const category =
    ext === ".png" || ext === ".jpg" || ext === ".jpeg" || ext === ".webp" || ext === ".gif"
      ? "image"
      : ext === ".xlsx" || ext === ".csv" || ext === ".tsv"
        ? "spreadsheet"
        : ext === ".py" || ext === ".ts" || ext === ".js" || ext === ".json" || ext === ".vue"
          ? "code"
          : "document";
  return {
    id: fileId,
    conversation_id: conversationId,
    filename: filename || "资料文件",
    ext,
    mime_type: "",
    category,
    size_bytes: 0,
    status: "ready",
    source: "user",
    is_global: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

function onSelectFileFromSearch(fileId: string, filename: string, conversationId: string | null) {
  activeView.value = "chat";
  onPreviewFile(buildSyntheticFile(fileId, filename, conversationId));
}

function onSelectMemoryFromSearch(_entryId: string) {
  void router.push({ path: "/settings", query: { tab: "memory" } });
}

function onJumpContextMessage(messageId: string) {
  contextStateOpen.value = false;
  focusMessageId.value = null;
  void Promise.resolve().then(() => {
    focusMessageId.value = messageId;
  });
}

async function onOpenCitation(citation: CitationItem) {
  const meta = citation.metadata ?? {};
  if (citation.source_type === "file") {
    const fileId = String(meta.file_id || citation.source_id || "").trim();
    const filename = String(meta.filename || citation.title || "资料文件").trim();
    if (!fileId) return;
    onPreviewFile(buildSyntheticFile(fileId, filename, meta.conversation_id ?? null));
    return;
  }
  if (citation.source_type === "chat_digest" || citation.source_type === "chat_turn") {
    const targetConvId = String(meta.conversation_id || citation.source_id || "").trim();
    if (!targetConvId) return;
    const msgId = meta.message_id ? String(meta.message_id) : null;
    await onSelectFromSearch(targetConvId, msgId);
  }
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
  if (switchToFilesTab) {
    previewTarget.value = null;
    showPlan.value = true;
    planTab.value = "files";
  }
  const started = await filesStore.enqueueFiles(fileList, ensureConversationId, dataTransfer);
  if (started && window.innerWidth >= 1024) {
    showPlan.value = true;
  }
}

async function onPasteFiles(files: File[]) {
  if (!agent.value?.ready || !files.length) return;
  await filesStore.enqueueFiles(files, ensureConversationId, null, {
    attachToBar: false,
    onTaskCreated(task) {
      chatInputRef.value?.insertUploadingChip(task);
    },
    onTaskCompleted(localId, completed) {
      chatInputRef.value?.resolveInlineUpload(localId, completed);
    },
    onTaskFailed(localId) {
      chatInputRef.value?.failInlineUpload(localId);
    },
  });
}

function onInsertFileToInput(file: ConversationFile) {
  chatInputRef.value?.insertFile(file);
  if (window.innerWidth < 1024) {
    mobileStepsOpen.value = false;
  }
}

async function onLocateFileMessage(file: ConversationFile) {
  if (!file.message_id) return;
  const targetConvId = file.conversation_id;
  if (targetConvId && targetConvId !== conversations.current?.id) {
    await onSelectFromSearch(targetConvId, file.message_id);
  } else {
    focusMessageId.value = null;
    await Promise.resolve();
    focusMessageId.value = file.message_id;
  }
  if (window.innerWidth < 1024) {
    mobileStepsOpen.value = false;
  }
}

function onMainFileScopeChange(nextScope: "all" | "conversation") {
  mainFileScope.value = nextScope;
  if (conversations.current?.id) {
    void filesStore.load(conversations.current.id, isMainChat.value ? nextScope : "conversation");
  }
}

async function onCreateWorkspaceFile(filename: string, content: string) {
  if (!agent.value?.ready) return;
  try {
    await filesStore.createTextFile(filename, content, ensureConversationId, false);
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "新建文件失败";
  }
}

async function onRenameWorkspaceFile(fileId: string, filename: string) {
  try {
    const target = filesStore.files.find((f) => f.id === fileId);
    await filesStore.renameFile(fileId, filename, target?.conversation_id ?? undefined);
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "重命名文件失败";
  }
}

function onOpenDeliverable(target: DeliverableTarget) {
  deliverableTarget.value = {
    ...target,
    conversationId: target.conversationId ?? conversations.current?.id ?? null,
  };
}

function onOpenLightbox(file: ConversationFile, siblings: ConversationFile[]) {
  const list = siblings.length ? siblings : [file];
  const idx = list.findIndex((f) => f.id === file.id);
  lightboxImages.value = list;
  lightboxIndex.value = idx >= 0 ? idx : 0;
  lightboxOpen.value = true;
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

async function onSend(content: string, inlineFileIds: string[] = []) {
  if (sendingMessage.value || chat.streaming || filesStore.hasActiveUploads) return;
  sendingMessage.value = true;
  try {
    await ensureConversationId();
    const barAttached = filesStore.attachedFiles;
    filesStore.consumeAttachedIds();
    const seen = new Set(barAttached.map((f) => f.id));
    const combined: ConversationFile[] = [...barAttached];
    for (const fid of inlineFileIds) {
      if (seen.has(fid)) continue;
      const found = filesStore.files.find((f) => f.id === fid);
      if (found) {
        seen.add(fid);
        combined.push(found);
      }
    }
    const skillNames = [...selectedSkills.value];
    selectedSkills.value = [];
    planTab.value = "steps";
    const sendPromise = chat.send(content, combined, skillNames);
    sendingMessage.value = false;
    await sendPromise;
    if (conversations.current?.id) {
      void filesStore.load(
        conversations.current.id,
        isMainChat.value ? mainFileScope.value : "conversation",
      );
    }
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
  } catch (e: any) {
    chat.error = e?.detail?.detail ?? e?.message ?? "重新生成失败，请稍后重试";
  }
}

async function onEditMessage(userMessageId: string, content: string) {
  if (chat.streaming || filesStore.hasActiveUploads) return;
  try {
    const original = chat.messages.find((m) => m.id === userMessageId && m.role === "user");
    const existingAttachments = original?.tool_payload?.attachments ?? [];
    const seenIds = new Set<string>();
    const resolvedAttached: ConversationFile[] = [];
    for (const att of existingAttachments) {
      if (seenIds.has(att.id)) continue;
      seenIds.add(att.id);
      const found = filesStore.files.find((f) => f.id === att.id);
      if (found) {
        resolvedAttached.push(found);
      } else {
        resolvedAttached.push({
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
        });
      }
    }
    for (const inlineId of extractFileIdsFromText(content)) {
      if (seenIds.has(inlineId)) continue;
      const found = filesStore.files.find((f) => f.id === inlineId);
      if (found) {
        seenIds.add(inlineId);
        resolvedAttached.push(found);
      }
    }
    const existingSkills = original?.tool_payload?.skills ?? [];
    await chat.editAndResend(userMessageId, content, resolvedAttached, existingSkills);
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

async function onResolveSchedule(id: string, action: "approve" | "reject") {
  const nextBusy = new Set(pendingBusyIds.value);
  nextBusy.add(id);
  pendingBusyIds.value = nextBusy;
  const { [id]: _, ...restErrors } = pendingErrors.value;
  pendingErrors.value = restErrors;
  try {
    await chat.resolvePendingSchedule(id, action);
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
  shell?.registerChatRailToggle(toggleSidebarCollapsed);
  const prefill = typeof route.query.prefill === "string" ? route.query.prefill.trim() : "";
  if (prefill) {
    const input = chatInputRef.value as any;
    if (input && typeof input.setText === "function") {
      input.setText(prefill);
    }
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
  window.removeEventListener("keydown", onGlobalKeydown);
  window.removeEventListener("resize", onWindowResize);
  window.removeEventListener("online", onOnlineRecovery);
  document.removeEventListener("visibilitychange", onVisibilityRecovery);
  mediaQuery?.removeEventListener("change", onMediaChange);
  if (pollTimer) window.clearTimeout(pollTimer);
  shell?.registerChatRailToggle(null);
  chat.abort();
});
</script>

<template>
  <div class="flex h-full min-w-0 flex-1 overflow-hidden bg-canvas">
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
      <!-- Chat Workspace View (Main Chat & Side Chats) -->
      <!-- Fixed task panel toggle (top-right inside panel when expanded, same position when collapsed) -->
      <button
        type="button"
        class="focus-ring absolute right-3.5 top-3.5 z-30 inline-flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
        :aria-label="showPlan ? '收起右侧栏' : '展开右侧栏'"
        :title="showPlan ? '收起右侧栏' : '展开右侧栏'"
        @click="onPlanToggleClick"
      >
        <AppIcon name="panel-right" :active="showPlan" class="h-[21px] w-[21px]" :stroke-width="1.95" />
        <span
          v-if="filesStore.fileCount > 0 && !showPlan"
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
            <AppIcon name="menu-lines" class="h-[22px] w-[22px]" :stroke-width="2.1" />
          </button>

          <h1 class="min-w-0 truncate text-[15.5px] font-semibold text-fg">
            {{ headerTitle }}
          </h1>
          <span
            v-if="activeView === 'chat' && isCurrentScheduled"
            class="inline-flex shrink-0 items-center gap-1 rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium text-fg-muted"
          >
            <AppIcon name="clock" motion="none" class="h-3 w-3 shrink-0" :stroke-width="2" />
            <span>定时</span>
          </span>
          <button
            v-if="conversations.current?.id"
            type="button"
            class="focus-ring pointer-events-auto ml-auto inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-surface/85 px-2.5 text-[12px] font-medium text-fg-muted backdrop-blur-sm transition-colors hover:bg-hover hover:text-fg"
            title="查看对话上下文记忆与归档状态"
            @click="contextStateOpen = true"
          >
            <AppIcon name="database" class="h-3.5 w-3.5" :stroke-width="1.9" />
            <span class="hidden sm:inline">上下文</span>
          </button>
        </div>

        <div class="relative min-h-0 flex-1">
          <MessageList
            v-if="chat.messages.length"
            ref="messageListRef"
            :key="chat.convId ?? 'draft'"
            :messages="chat.messages"
            :focus-message-id="focusMessageId"
            :downloading-file-id="downloadingFileId"
            :bottom-inset="bottomOverlayHeight"
            @steps="onViewSteps"
            @focus-handled="focusMessageId = null"
            @regenerate="onRegenerate"
            @edit="onEditMessage"
            @preview-html="onPreviewHtml"
            @preview-file="onPreviewFile"
            @open-deliverable="onOpenDeliverable"
            @open-lightbox="onOpenLightbox"
            @download-file="onDownloadFile"
            @open-citation="onOpenCitation"
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
        <div
          class="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-transparent px-3 pb-4 pt-2 sm:px-6 sm:pb-5"
        >
          <div class="mx-auto flex w-full max-w-4xl flex-col gap-3">
            <div class="pointer-events-none flex justify-center">
              <div class="pointer-events-auto">
                <ScrollToBottomButton
                  :visible="Boolean(chat.messages.length && messageListRef?.showJumpToBottom)"
                  :streaming="chat.streaming"
                  :scroll-container="messageListRef?.scrollContainer ?? null"
                  @click="messageListRef?.jumpToBottom()"
                />
              </div>
            </div>

            <div ref="bottomOverlayRef" class="pointer-events-auto w-full space-y-3">
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

            <SchedulePendingCard
              v-for="item in chat.pendingSchedules"
              :key="`sched-${item.id}`"
              :item="item"
              :busy="pendingBusyIds.has(item.id)"
              :error="pendingErrors[item.id] ?? null"
              @resolve="onResolveSchedule"
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
                  <AppIcon name="close" class="h-3.5 w-3.5" :stroke-width="2" />
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
                  <AppIcon name="close" class="h-3.5 w-3.5" :stroke-width="2" />
                </button>
              </div>
            </Transition>

            <ChatInput
              ref="chatInputRef"
              v-model:selected-skills="selectedSkills"
              :streaming="chat.streaming"
              :sending="sendingMessage || chat.waitingFirstByte"
              :stopping="chat.stopping"
              :disabled="!agent?.ready"
              :uploading="filesStore.hasActiveUploads"
              :uploads="filesStore.uploads"
              :attached-files="filesStore.attachedFiles"
              :workspace-files="filesStore.files"
              :assistant-name="assistantName"
              @send="onSend"
              @stop="chat.stop"
              @upload="(files, dt) => onUploadFiles(files, dt, false)"
              @paste-files="onPasteFiles"
              @cancel-upload="filesStore.cancelUpload"
              @dismiss-upload="filesStore.dismissUpload"
              @retry-upload="onRetryUpload"
              @detach-file="filesStore.detachFile"
            />
            </div>
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
            :file-scope="mainFileScope"
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
            @update:file-scope="onMainFileScopeChange"
            @upload="(files, dt) => onUploadFiles(files, dt, true)"
            @cancel-upload="filesStore.cancelUpload"
            @dismiss-upload="filesStore.dismissUpload"
            @retry-upload="onRetryUpload"
            @delete-file="onDeleteFile"
            @download-file="onDownloadFile"
            @preview-file="onPreviewFile"
            @open-deliverable="onOpenDeliverable"
            @open-lightbox="onOpenLightbox"
            @insert-file="onInsertFileToInput"
            @locate-file-message="onLocateFileMessage"
            @rename-file="onRenameWorkspaceFile"
            @create-file="onCreateWorkspaceFile"
            @close-preview="closePreview"
            @attach-library="onAttachLibraryFiles"
          />
        </div>
      </aside>
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
              <AppIcon name="close" class="h-4.5 w-4.5" :stroke-width="2" />
            </button>
          </div>
          <div class="min-h-0 flex-1">
            <PlanPanel
              v-model:active-tab="planTab"
              :file-scope="mainFileScope"
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
              @update:file-scope="onMainFileScopeChange"
              @upload="(files, dt) => onUploadFiles(files, dt, true)"
              @cancel-upload="filesStore.cancelUpload"
              @dismiss-upload="filesStore.dismissUpload"
              @retry-upload="onRetryUpload"
              @delete-file="onDeleteFile"
              @download-file="onDownloadFile"
              @preview-file="onPreviewFile"
              @open-deliverable="onOpenDeliverable"
              @open-lightbox="onOpenLightbox"
              @insert-file="onInsertFileToInput"
              @locate-file-message="onLocateFileMessage"
              @rename-file="onRenameWorkspaceFile"
              @create-file="onCreateWorkspaceFile"
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
      @select-file="onSelectFileFromSearch"
      @select-memory="onSelectMemoryFromSearch"
    />
    <ContextStateModal
      :open="contextStateOpen"
      :conversation-id="conversations.current?.id ?? null"
      :conversation-title="headerTitle"
      @close="contextStateOpen = false"
      @jump-message="onJumpContextMessage"
      @open-memory-settings="contextStateOpen = false; router.push({ path: '/settings', query: { tab: 'memory' } })"
    />
    <DeliverableModal
      :target="deliverableTarget"
      @close="deliverableTarget = null"
    />
    <ImageLightboxModal
      :open="lightboxOpen"
      :images="lightboxImages"
      :initial-index="lightboxIndex"
      @close="lightboxOpen = false"
      @download="onDownloadFile"
    />
  </div>
</template>
