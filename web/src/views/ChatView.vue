<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useConversationsStore } from "../stores/conversations";
import { useChatStore } from "../stores/chat";
import { useAuthStore } from "../stores/auth";
import { useCreditsStore } from "../stores/credits";
import { api } from "../api/client";
import type { AgentStatus } from "../types";
import ConversationSidebar from "../components/chat/ConversationSidebar.vue";
import MessageList from "../components/chat/MessageList.vue";
import ChatInput from "../components/chat/ChatInput.vue";
import PlanPanel from "../components/chat/PlanPanel.vue";
import ApprovalCard from "../components/chat/ApprovalCard.vue";
import ClarifyCard from "../components/chat/ClarifyCard.vue";

const conversations = useConversationsStore();
const chat = useChatStore();
const auth = useAuthStore();
const credits = useCreditsStore();

const agent = ref<AgentStatus | null>(null);
const showPlan = ref(false);
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(false);
const mobileStepsOpen = ref(false);
let pollTimer: number | null = null;

function setSidebarCollapsed(next: boolean) {
  sidebarCollapsed.value = next;
}

function toggleSidebarCollapsed() {
  setSidebarCollapsed(!sidebarCollapsed.value);
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

async function openConversation(id: string) {
  const detail = await conversations.open(id);
  chat.loadFromConversation(detail);
}

function createConversation() {
  chat.abort();
  conversations.clearCurrent();
  chat.reset();
  showPlan.value = false;
}

async function onSelect(id: string) {
  sidebarOpen.value = false;
  mobileStepsOpen.value = false;
  if (id === conversations.current?.id) return;
  chat.abort();
  await openConversation(id);
  showPlan.value = true;
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
      await openConversation(conversations.conversations[0].id);
      showPlan.value = true;
    } else {
      conversations.clearCurrent();
      showPlan.value = false;
    }
  }
}

async function onSend(content: string) {
  if (chat.streaming) return;
  try {
    if (!conversations.current) {
      const conv = await conversations.create();
      await openConversation(conv.id);
    }
    await chat.send(content);
    await conversations.fetchList();
  } catch (e: any) {
    chat.error = e?.detail?.detail ?? e?.message ?? "无法开始对话，请稍后重试";
  }
}

function onViewSteps(id: string) {
  chat.selectTurn(id);
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

onMounted(async () => {
  window.addEventListener("keydown", onGlobalKeydown);
  void loadAgent();
  void credits.fetch();
  await conversations.fetchList();
  conversations.clearCurrent();
  chat.reset();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  if (pollTimer) window.clearTimeout(pollTimer);
  chat.abort();
});
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-canvas">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="sidebarOpen" class="fixed inset-0 z-30 bg-black/40 md:hidden" @click="sidebarOpen = false" />
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
      @set-collapsed="setSidebarCollapsed"
    />

    <main class="relative flex min-w-0 flex-1">
      <!-- Fixed task panel toggle (top-right inside panel when expanded, same position when collapsed) -->
      <button
        type="button"
        class="focus-ring absolute right-3.5 top-3.5 z-30 hidden h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg lg:inline-flex"
        :aria-label="showPlan ? '收起任务面板' : '展开任务面板'"
        :title="showPlan ? '收起任务面板' : '展开任务面板'"
        @click="showPlan = !showPlan"
      >
        <svg class="h-[21px] w-[21px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 5h18v14H3zM15 5v14" />
        </svg>
      </button>

      <div class="relative flex min-w-0 flex-1 flex-col">
        <!-- Progressive blur top zone + floating sidebar toggle & conversation title -->
        <div class="progressive-blur-top pointer-events-none absolute inset-x-0 top-0 z-20 h-20" />
        <div
          class="pointer-events-none absolute inset-x-0 top-0 z-30 flex items-center gap-2.5 px-3.5 pt-3.5"
          :class="showPlan ? 'pr-4' : 'lg:pr-16'"
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
            @steps="onViewSteps"
          />

          <div v-else v-scrollbar class="custom-scrollbar h-full overflow-y-auto">
            <div class="flex min-h-full flex-col items-center justify-center px-4 pb-4 pt-32 sm:px-6 sm:pt-40">
              <div class="w-full max-w-2xl text-center">
                <div class="inline-flex items-center justify-center gap-3.5">
                  <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-[14px] bg-primary text-primary-fg sm:h-11 sm:w-11"
                  >
                    <span class="text-[18px] font-semibold tracking-tight sm:text-[20px]">W</span>
                  </div>
                  <h1 class="text-[32px] font-semibold leading-10 tracking-tight text-fg sm:text-[38px] sm:leading-[44px]">
                    {{ greeting }}<template v-if="userName">，{{ userName }}</template>
                  </h1>
                </div>
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

        <div class="shrink-0 px-3 pb-4 pt-1 sm:px-6 sm:pb-5">
          <div class="mx-auto w-full max-w-4xl space-y-3">
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

            <ChatInput :streaming="chat.streaming" :disabled="!agent?.ready" @send="onSend" @stop="chat.stop" />
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
            :plan="chat.viewPlan"
            :reasoning="chat.viewReasoning"
            :streaming="chat.viewStreaming"
            :current-step="chat.viewCurrentStep"
            :running-tool="chat.viewRunningTool"
            :turn-key="chat.selectedTurn?.id ?? ''"
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
          <div class="flex h-11 shrink-0 items-center justify-between pl-4 pr-2">
            <span class="text-[12px] font-medium text-fg">本轮步骤</span>
            <button
              type="button"
              class="flex h-8 w-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              aria-label="关闭步骤面板"
              @click="mobileStepsOpen = false"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div class="min-h-0 flex-1">
            <PlanPanel
              :plan="chat.viewPlan"
              :reasoning="chat.viewReasoning"
              :streaming="chat.viewStreaming"
              :current-step="chat.viewCurrentStep"
              :running-tool="chat.viewRunningTool"
              :turn-key="chat.selectedTurn?.id ?? ''"
            />
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
