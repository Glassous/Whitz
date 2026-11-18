<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useConversationsStore } from "../stores/conversations";
import { useChatStore } from "../stores/chat";
import { useAuthStore } from "../stores/auth";
import { useCreditsStore } from "../stores/credits";
import { useFilesStore } from "../stores/files";
import { api } from "../api/client";
import type { AgentStatus, ConversationFile, TaskPanelTab } from "../types";
import ConversationSidebar from "../components/chat/ConversationSidebar.vue";
import MessageList from "../components/chat/MessageList.vue";
import ChatInput from "../components/chat/ChatInput.vue";
import PlanPanel from "../components/chat/PlanPanel.vue";
import ApprovalCard from "../components/chat/ApprovalCard.vue";
import ClarifyCard from "../components/chat/ClarifyCard.vue";
import SearchModal from "../components/chat/SearchModal.vue";

const route = useRoute();
const router = useRouter();
const conversations = useConversationsStore();
const chat = useChatStore();
const auth = useAuthStore();
const credits = useCreditsStore();
const filesStore = useFilesStore();

const routeConversationId = computed(() => (typeof route.params.id === "string" && route.params.id ? route.params.id : null));

const agent = ref<AgentStatus | null>(null);
const showPlan = ref(false);
const planTab = ref<TaskPanelTab>("steps");
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(false);
const drawerDragProgress = ref<number | null>(null);
const mobileStepsOpen = ref(false);
const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;
function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
  if (e.matches) sidebarOpen.value = false;
}
const searchOpen = ref(false);
const focusMessageId = ref<string | null>(null);
let pollTimer: number | null = null;

function setSidebarCollapsed(next: boolean) {
  sidebarCollapsed.value = next;
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
  try {
    const detail = await conversations.open(id);
    chat.loadFromConversation(detail);
    void filesStore.load(id);
    return true;
  } catch {
    conversations.clearCurrent();
    chat.reset();
    filesStore.reset();
    return false;
  }
}

function createConversation() {
  chat.abort();
  conversations.clearCurrent();
  chat.reset();
  filesStore.reset();
  showPlan.value = false;
  planTab.value = "steps";
  if (routeConversationId.value) {
    void router.push({ name: "chat" });
  }
}

async function onSelect(id: string) {
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
  const ok = await openConversation(id);
  if (ok) {
    showPlan.value = true;
    if (routeConversationId.value !== id) {
      void router.push({ name: "chat-conversation", params: { id } });
    }
  }
}

async function onSelectFromSearch(conversationId: string, messageId: string | null) {
  sidebarOpen.value = false;
  mobileStepsOpen.value = false;
  if (conversationId !== conversations.current?.id) {
    chat.abort();
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

async function onDelete(id: string) {
  const wasCurrent = conversations.current?.id === id;
  await conversations.remove(id);
  if (wasCurrent) {
    chat.reset();
    if (conversations.conversations.length) {
      const nextId = conversations.conversations[0].id;
      const ok = await openConversation(nextId);
      if (ok) {
        showPlan.value = true;
        void router.replace({ name: "chat-conversation", params: { id: nextId } });
      } else {
        void router.replace({ name: "chat" });
      }
    } else {
      conversations.clearCurrent();
      filesStore.reset();
      showPlan.value = false;
      void router.replace({ name: "chat" });
    }
  }
}

async function ensureConversationId(): Promise<string> {
  if (conversations.current?.id) return conversations.current.id;
  const conv = await conversations.create();
  await openConversation(conv.id);
  void router.replace({ name: "chat-conversation", params: { id: conv.id } });
  return conv.id;
}

async function onUploadFiles(fileList: FileList, dataTransfer?: DataTransfer | null, switchToFilesTab = false) {
  if (!agent.value?.ready) return;
  if (switchToFilesTab) {
    showPlan.value = true;
    planTab.value = "files";
  }
  const started = await filesStore.enqueueFiles(fileList, ensureConversationId, dataTransfer);
  if (started && window.innerWidth >= 1024) {
    showPlan.value = true;
  }
}

async function onDeleteFile(fileId: string) {
  try {
    await filesStore.removeFile(fileId);
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "删除文件失败";
  }
}

async function onDownloadFile(file: ConversationFile) {
  try {
    const url = await filesStore.getDownloadUrl(file.id, false);
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  } catch (e: any) {
    filesStore.error = e?.detail?.detail ?? e?.message ?? "获取下载链接失败";
  }
}

async function onSend(content: string) {
  if (chat.streaming || filesStore.hasActiveUploads) return;
  try {
    await ensureConversationId();
    const attached = filesStore.attachedFiles;
    filesStore.consumeAttachedIds();
    planTab.value = "steps";
    await chat.send(content, attached);
    await conversations.fetchList();
  } catch (e: any) {
    chat.error = e?.detail?.detail ?? e?.message ?? "无法开始对话，请稍后重试";
  }
}

function onViewSteps(id: string) {
  chat.selectTurn(id);
  planTab.value = "steps";
  showPlan.value = true;
  if (window.innerWidth < 1024) mobileStepsOpen.value = true;
}

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

watch(routeConversationId, async (nextId) => {
  if (nextId) {
    if (nextId !== conversations.current?.id) {
      chat.abort();
      const ok = await openConversation(nextId);
      if (ok) {
        showPlan.value = true;
      } else {
        showPlan.value = false;
        void router.replace({ name: "chat" });
      }
    }
  } else if (conversations.current) {
    chat.abort();
    conversations.clearCurrent();
    chat.reset();
    filesStore.reset();
    showPlan.value = false;
  }
});

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKeydown);
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  void loadAgent();
  void credits.fetch();
  await conversations.fetchList();
  if (routeConversationId.value) {
    const ok = await openConversation(routeConversationId.value);
    if (ok) {
      showPlan.value = true;
    } else {
      showPlan.value = false;
      void router.replace({ name: "chat" });
    }
  } else {
    conversations.clearCurrent();
    chat.reset();
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  mediaQuery?.removeEventListener("change", onMediaChange);
  if (pollTimer) window.clearTimeout(pollTimer);
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
      :conversations="conversations.conversations"
      :current-id="conversations.current?.id ?? null"
      :loading="conversations.loading"
      :open="sidebarOpen"
      :collapsed="sidebarCollapsed"
      @select="onSelect"
      @create="createConversation"
      @rename="onRename"
      @delete="onDelete"
      @close="sidebarOpen = false"
      @open-search="searchOpen = true"
      @drag-progress="drawerDragProgress = $event"
    />

    <main class="relative flex min-w-0 flex-1" :inert="(!isDesktop && sidebarOpen) || undefined">
      <!-- Fixed task panel toggle (top-right inside panel when expanded, same position when collapsed) -->
      <button
        type="button"
        class="focus-ring absolute right-3.5 top-3.5 z-30 inline-flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
        :aria-label="showPlan ? '收起任务面板' : '展开任务面板'"
        :title="showPlan ? '收起任务面板' : '展开任务面板'"
        @click="onPlanToggleClick"
      >
        <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 5h18v14H3zM15 5v14" />
        </svg>
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
            <svg class="h-[22px] w-[22px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3">
              <path stroke-linecap="round" d="M4 8.5h16M4 15.5h10" />
            </svg>
          </button>

          <h1 class="min-w-0 truncate text-[15.5px] font-semibold text-fg">
            {{ conversations.current?.title ?? "新对话" }}
          </h1>
        </div>

        <div class="relative min-h-0 flex-1">
          <MessageList
            v-if="chat.messages.length"
            :key="chat.convId ?? 'draft'"
            :messages="chat.messages"
            :focus-message-id="focusMessageId"
            @steps="onViewSteps"
            @focus-handled="focusMessageId = null"
          />

          <div v-else v-scrollbar class="custom-scrollbar h-full overflow-y-auto">
            <div class="flex min-h-full flex-col items-center justify-center px-4 pb-32 pt-32 sm:px-6 sm:pt-40">
              <div class="w-full max-w-2xl text-center">
                <h1 class="text-[32px] font-semibold leading-10 tracking-tight text-fg sm:text-[38px] sm:leading-[44px]">
                  {{ greeting }}<template v-if="userName">，{{ userName }}</template>
                </h1>
                <p class="mx-auto mt-3.5 max-w-lg text-[16px] text-fg-muted sm:text-[17px]">
                  我可以帮你规划任务、联网检索、整理信息。今天想做点什么？
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
                @decide="chat.approve"
              />
              <ClarifyCard
                v-else-if="chat.pendingControl?.kind === 'clarify'"
                :control="chat.pendingControl"
                @submit="chat.clarify"
              />
            </Transition>

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
              :streaming="chat.streaming"
              :disabled="!agent?.ready"
              :uploading="filesStore.hasActiveUploads"
              :uploads="filesStore.uploads"
              :attached-files="filesStore.attachedFiles"
              @send="onSend"
              @stop="chat.stop"
              @upload="(files, dt) => onUploadFiles(files, dt, false)"
              @cancel-upload="filesStore.cancelUpload"
              @dismiss-upload="filesStore.dismissUpload"
              @detach-file="filesStore.detachFile"
            />
          </div>
        </div>
      </div>

      <aside
        class="hidden h-full shrink-0 overflow-hidden bg-sidebar transition-[width,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] lg:block"
        :class="showPlan ? 'w-[320px] opacity-100' : 'pointer-events-none w-0 opacity-0'"
        :aria-hidden="!showPlan"
      >
        <div class="h-full w-[320px]">
          <PlanPanel
            v-model:active-tab="planTab"
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
            @upload="(files, dt) => onUploadFiles(files, dt, true)"
            @cancel-upload="filesStore.cancelUpload"
            @dismiss-upload="filesStore.dismissUpload"
            @delete-file="onDeleteFile"
            @download-file="onDownloadFile"
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
      <div v-if="mobileStepsOpen" class="fixed inset-0 z-40 lg:hidden">
        <div class="absolute inset-0 bg-black/40" @click="mobileStepsOpen = false" />
        <div class="absolute inset-y-0 right-0 flex w-[min(360px,90vw)] flex-col bg-sidebar shadow-2xl transition-transform duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]">
          <div class="flex h-13 shrink-0 items-center justify-between pl-4 pr-2.5">
            <h3 class="text-[16px] font-semibold text-fg">任务面板</h3>
            <button
              type="button"
              class="focus-ring flex h-9 w-9 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              aria-label="关闭任务面板"
              @click="mobileStepsOpen = false"
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
              @upload="(files, dt) => onUploadFiles(files, dt, true)"
              @cancel-upload="filesStore.cancelUpload"
              @dismiss-upload="filesStore.dismissUpload"
              @delete-file="onDeleteFile"
              @download-file="onDownloadFile"
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
