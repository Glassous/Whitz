<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useConversationsStore } from "../stores/conversations";
import { useChatStore } from "../stores/chat";
import { useAuthStore } from "../stores/auth";
import { api } from "../api/client";
import type { AgentStatus } from "../types";
import ConversationSidebar from "../components/chat/ConversationSidebar.vue";
import MessageList from "../components/chat/MessageList.vue";
import ChatInput from "../components/chat/ChatInput.vue";
import PlanPanel from "../components/chat/PlanPanel.vue";
import ApprovalCard from "../components/chat/ApprovalCard.vue";
import ClarifyCard from "../components/chat/ClarifyCard.vue";
import ThemeToggle from "../components/ui/ThemeToggle.vue";

const conversations = useConversationsStore();
const chat = useChatStore();
const auth = useAuthStore();

const agent = ref<AgentStatus | null>(null);
const showPlan = ref(true);
const sidebarOpen = ref(false);
const mobileStepsOpen = ref(false);
let pollTimer: number | null = null;

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

const statusText = computed(() =>
  agent.value?.ready ? "在线" : agent.value?.status === "warming_up" ? "初始化中" : "离线",
);

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
}

async function onSelect(id: string) {
  sidebarOpen.value = false;
  mobileStepsOpen.value = false;
  if (id === conversations.current?.id) return;
  chat.abort();
  await openConversation(id);
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
    } else {
      conversations.clearCurrent();
    }
  }
}

function suggestTitle(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > 24 ? t.slice(0, 24) + "…" : t;
}

async function onSend(content: string) {
  if (chat.streaming) return;
  try {
    if (!conversations.current) {
      const conv = await conversations.create();
      await openConversation(conv.id);
    }
    const current = conversations.current;
    const fresh = !!current && current.messages.length === 0;
    if (current && fresh && current.title === "新对话") {
      void conversations.rename(current.id, suggestTitle(content)).catch(() => {});
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
    if (old && !val) void conversations.fetchList();
  },
);

onMounted(async () => {
  void loadAgent();
  await conversations.fetchList();
  conversations.clearCurrent();
  chat.reset();
});

onBeforeUnmount(() => {
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
      @select="onSelect"
      @create="createConversation"
      @rename="onRename"
      @delete="onDelete"
      @close="sidebarOpen = false"
    />

    <main class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3 sm:px-5">
        <button
          class="focus-ring -ml-1 flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg md:hidden"
          aria-label="打开侧栏"
          @click="sidebarOpen = true"
        >
          <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
            <path stroke-linecap="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        <div class="flex min-w-0 items-center gap-2.5">
          <h1 class="truncate text-[14px] font-medium text-fg">
            {{ conversations.current?.title ?? "新对话" }}
          </h1>
          <span class="hidden items-center gap-1.5 text-[11px] text-fg-faint sm:flex">
            <span
              class="h-1.5 w-1.5 rounded-full"
              :class="
                agent?.ready
                  ? 'bg-success'
                  : agent?.status === 'warming_up'
                    ? 'animate-pulse bg-warning'
                    : 'bg-line-strong'
              "
            />
            {{ statusText }}
          </span>
        </div>

        <div class="ml-auto flex items-center gap-1">
          <button
            class="focus-ring hidden h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium transition-colors lg:inline-flex"
            :class="showPlan ? 'bg-surface text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
            @click="showPlan = !showPlan"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 5h18v14H3zM15 5v14" />
            </svg>
            任务面板
          </button>
          <div class="md:hidden"><ThemeToggle /></div>
        </div>
      </header>

      <div class="flex min-h-0 flex-1">
        <div class="flex min-w-0 flex-1 flex-col">
          <div class="relative min-h-0 flex-1">
            <MessageList
              v-if="chat.messages.length"
              :key="chat.convId ?? 'draft'"
              :messages="chat.messages"
              @steps="onViewSteps"
            />

            <div v-else class="h-full overflow-y-auto">
              <div class="flex min-h-full flex-col items-center justify-center px-4 py-10 sm:px-6">
                <div class="animate-rise w-full max-w-2xl text-center">
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
                      class="focus-ring group flex items-start gap-3 rounded-2xl border border-line bg-canvas p-3.5 text-left transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="!agent?.ready"
                      @click="startWith(s.prompt)"
                    >
                      <span
                        class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface text-fg-muted transition-colors group-hover:bg-canvas group-hover:text-fg"
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

                  <p v-if="!agent?.ready" class="mt-6 text-xs text-fg-faint">助理正在初始化，稍后即可开始对话…</p>
                </div>
              </div>
            </div>
          </div>

          <div class="shrink-0 px-3 pb-3 pt-1 sm:px-6">
            <div class="mx-auto w-full max-w-3xl space-y-3">
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

        <aside v-if="showPlan" class="hidden w-[320px] shrink-0 border-l border-line bg-sidebar lg:block">
          <PlanPanel
            :plan="chat.viewPlan"
            :reasoning="chat.viewReasoning"
            :streaming="chat.viewStreaming"
            :current-step="chat.viewCurrentStep"
            :running-tool="chat.viewRunningTool"
            :turn-key="chat.selectedTurn?.id ?? ''"
          />
        </aside>
      </div>
    </main>

    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="mobileStepsOpen" class="fixed inset-0 z-40 lg:hidden">
        <div class="absolute inset-0 bg-black/40" @click="mobileStepsOpen = false" />
        <div class="absolute inset-y-0 right-0 flex w-[min(360px,90vw)] flex-col bg-sidebar shadow-2xl">
          <div class="flex h-11 shrink-0 items-center justify-between border-b border-line pl-4 pr-2">
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
