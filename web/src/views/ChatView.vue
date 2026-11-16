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

const SIDEBAR_COLLAPSED_KEY = "whitz_sidebar_collapsed";

function readCollapsedPref(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

const agent = ref<AgentStatus | null>(null);
const showPlan = ref(false);
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(readCollapsedPref());
const mobileStepsOpen = ref(false);
let pollTimer: number | null = null;

function setSidebarCollapsed(next: boolean) {
  sidebarCollapsed.value = next;
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
  } catch {
    /* ignore */
  }
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

const SUGGESTIONS = [
  {
    title: "制定一周学习计划",
    desc: "先规划步骤，再逐步执行",
    prompt: "帮我制定一份一周学习计划，并给出每天的具体安排。",
    icon: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z",
  },
  {
    title: "调研一个主题",
    desc: "联网检索并汇总关键信息",
    prompt: "帮我调研一下最近一年 AI Agent 领域的重要进展，并给出总结。",
    icon: "M21 21l-4.3-4.3M11 19a8 8 0 100-16 8 8 0 000 16z",
  },
  {
    title: "整理零散想法",
    desc: "梳理成结构化方案",
    prompt: "我有一些零散的想法，想请你帮我梳理成一个结构化的方案。",
    icon: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z",
  },
  {
    title: "写一段文案",
    desc: "起草并润色文字",
    prompt: "帮我写一段介绍个人 AI 助理产品的文案，风格简洁专业。",
    icon: "M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4 12.5-12.5z",
  },
];

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

function startWith(text: string) {
  if (!agent.value?.ready || chat.streaming) return;
  void onSend(text);
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
            <div class="flex min-h-full flex-col items-center justify-center px-4 pb-10 pt-20 sm:px-6">
              <div class="w-full max-w-2xl text-center">
                <div class="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-fg">
                  <span class="text-lg font-semibold tracking-tight">W</span>
                </div>
                <h1 class="text-[26px] font-semibold tracking-tight text-fg sm:text-[30px]">
                  {{ greeting }}<template v-if="userName">，{{ userName }}</template>
                </h1>
                <p class="mx-auto mt-2 max-w-md text-[14px] text-fg-muted">
                  我可以帮你规划任务、联网检索、整理信息。今天想做点什么？
                </p>

                <div class="mt-8 grid gap-2 sm:grid-cols-2">
                  <button
                    v-for="s in SUGGESTIONS"
                    :key="s.title"
                    class="focus-ring group flex items-start gap-3 rounded-2xl bg-surface/75 p-3.5 text-left transition-colors hover:bg-hover disabled:cursor-not-allowed"
                    :class="agent && !agent.ready ? 'opacity-50' : ''"
                    :disabled="!agent?.ready"
                    @click="startWith(s.prompt)"
                  >
                    <span
                      class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-fg-muted transition-colors group-hover:text-fg"
                    >
                      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                        <path stroke-linecap="round" stroke-linejoin="round" :d="s.icon" />
                      </svg>
                    </span>
                    <span class="min-w-0">
                      <span class="block text-[13px] font-medium text-fg">{{ s.title }}</span>
                      <span class="mt-0.5 block text-xs text-fg-faint">{{ s.desc }}</span>
                    </span>
                  </button>
                </div>

                <p
                  class="mt-6 h-4 text-xs text-fg-faint transition-opacity duration-200"
                  :class="agent && !agent.ready ? 'opacity-100' : 'pointer-events-none opacity-0'"
                >
                  助理正在初始化，稍后即可开始对话…
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="shrink-0 px-3 pb-3 pt-1 sm:px-6">
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
