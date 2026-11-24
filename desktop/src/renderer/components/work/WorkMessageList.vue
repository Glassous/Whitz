<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onBeforeUpdate, onMounted, ref, watch } from "vue";
import type { WorkMessage, WorkTokenUsage } from "@shared/work-types";
import { useDesktopStore } from "../../stores/desktop";
import { useWorkStore } from "../../stores/work";
import { useSmartStreamScroll } from "@web/composables/useSmartStreamScroll";
import MarkdownRenderer from "@web/components/chat/MarkdownRenderer.vue";

const TOP_CLEARANCE = 16;
const DEFAULT_BOTTOM_GAP = 160;

const props = defineProps<{
  conversationId: string | null;
  messages: WorkMessage[];
  activeAssistantId: string | null;
  selectedTurnId: string | null;
  streaming: boolean;
  revertedCount?: number;
  projectName?: string | null;
  bottomInset?: number;
}>();

const emit = defineEmits<{
  openFile: [string];
  revert: [string];
  unrevert: [];
  fork: [string];
  steps: [string];
  sendToChat: [string];
}>();

const desktop = useDesktopStore();
const work = useWorkStore();
const scroller = ref<HTMLElement | null>(null);
const wrapper = ref<HTMLElement | null>(null);
const itemRefs = ref<(HTMLElement | null)[]>([]);
const copiedId = ref<string | null>(null);
const expandedUserIds = ref<Set<string>>(new Set());

const baseBottomGap = computed(() => Math.max(DEFAULT_BOTTOM_GAP, (props.bottomInset ?? 0) + 24));
const extraTurnSpacer = ref(0);
let turnRevealActive = false;
let turnRevealInitialized = false;
let resizeObserver: ResizeObserver | null = null;

const smartScroll = useSmartStreamScroll(scroller);

function isLongUserInput(content: string): boolean {
  if (!content) return false;
  if (content.length >= 320) return true;
  return content.split("\n").length >= 7;
}

function isUserExpanded(id: string): boolean {
  return expandedUserIds.value.has(id);
}

function toggleUserExpand(id: string) {
  const next = new Set(expandedUserIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedUserIds.value = next;
}

const visibleMessages = computed(() => props.messages.filter((m) => m.role !== "tool"));

const latestTurnStartIndex = computed(() => {
  const msgs = visibleMessages.value;
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === "user") return i;
  }
  return msgs.length > 0 ? msgs.length - 1 : -1;
});

onBeforeUpdate(() => {
  itemRefs.value = [];
});

function setItemRef(index: number, el: HTMLElement | null) {
  itemRefs.value[index] = el;
}

function attachmentsOf(message: WorkMessage): Array<{ name: string; kind: string }> {
  const value = message.tool_payload?.attachments;
  return Array.isArray(value) ? (value as Array<{ name: string; kind: string }>) : [];
}

function usageOf(message: WorkMessage): WorkTokenUsage | null {
  const value = message.tool_payload?.usage;
  if (!value || typeof value !== "object") return null;
  const u = value as WorkTokenUsage;
  return typeof u.total === "number" && u.total > 0 ? u : null;
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function isLiveMessage(message: WorkMessage): boolean {
  return message.status === "streaming" || message.status === "waiting";
}

function stepCountOf(message: WorkMessage): number {
  return work.getTurnTimeline(message, props.messages).length;
}

function liveLabelOf(message: WorkMessage): string {
  return work.getTurnLiveLabel(message);
}

async function copyText(id: string, content: string) {
  if (!content) return;
  try {
    await navigator.clipboard.writeText(content);
    copiedId.value = id;
    setTimeout(() => {
      if (copiedId.value === id) copiedId.value = null;
    }, 1800);
  } catch {
    /* ignore */
  }
}

function measureTurnSpacer(): { el: HTMLElement; targetTop: number } | null {
  const el = scroller.value;
  const idx = latestTurnStartIndex.value;
  const startEl = idx >= 0 ? itemRefs.value[idx] : null;
  const lastEl = itemRefs.value[visibleMessages.value.length - 1];
  if (!el || !startEl || !lastEl) {
    extraTurnSpacer.value = 0;
    turnRevealActive = false;
    return null;
  }
  const targetTop = startEl.offsetTop;
  if (!turnRevealActive) {
    return { el, targetTop };
  }
  const contentBottom = lastEl.offsetTop + lastEl.offsetHeight;
  const latestTurnHeight = Math.max(0, contentBottom - targetTop);
  const usableHeight = Math.max(0, el.clientHeight - TOP_CLEARANCE - baseBottomGap.value);
  const needed = Math.max(0, usableHeight - latestTurnHeight);
  const nextExtra = turnRevealInitialized ? Math.min(extraTurnSpacer.value, needed) : needed;
  turnRevealInitialized = true;
  if (Math.abs(extraTurnSpacer.value - nextExtra) > 0.5) {
    extraTurnSpacer.value = nextExtra;
  }
  if (nextExtra <= 0.5) {
    extraTurnSpacer.value = 0;
    turnRevealActive = false;
  }
  return { el, targetTop };
}

async function scrollToLatestTurnTop() {
  turnRevealActive = latestTurnStartIndex.value > 0;
  turnRevealInitialized = false;
  smartScroll.autoFollow.value = true;
  await nextTick();
  const measured = measureTurnSpacer();
  await nextTick();
  if (!measured) return;
  if (turnRevealActive) {
    smartScroll.scrollToTopPosition(Math.max(0, measured.targetTop - TOP_CLEARANCE));
  } else {
    smartScroll.jumpToBottom("smooth");
  }
}

function scrollToBottom(force = false) {
  if (force) {
    smartScroll.jumpToBottom("smooth");
  } else if (smartScroll.autoFollow.value) {
    smartScroll.followBottomSmooth();
  }
}

// Switch conversation -> reset spacer & land cleanly at bottom
watch(
  () => props.conversationId,
  async () => {
    turnRevealActive = false;
    turnRevealInitialized = false;
    extraTurnSpacer.value = 0;
    await nextTick();
    smartScroll.jumpToBottom("instant");
  },
  { immediate: true },
);

// Explicit new turn (send / slash / shell / steer) -> Top-anchored turn reveal
watch(
  () => work.latestTurnTriggerSeq,
  async (seq) => {
    if (seq > 0) {
      await scrollToLatestTurnTop();
    }
  },
);

watch(
  () => {
    const lastVisible = visibleMessages.value[visibleMessages.value.length - 1];
    const stepLen = lastVisible?.role === "assistant" ? stepCountOf(lastVisible) : 0;
    return [
      visibleMessages.value.length,
      lastVisible?.id ?? "",
      lastVisible?.content.length ?? 0,
      lastVisible?.status ?? "",
      stepLen,
    ] as const;
  },
  async () => {
    await nextTick();
    measureTurnSpacer();
    await nextTick();
    if (smartScroll.autoFollow.value) {
      smartScroll.followBottomSmooth();
    } else {
      smartScroll.syncVisibility();
    }
  },
  { flush: "post" },
);

// Bottom overlay height changes (ApprovalSheet popping up, error banner, expanding composer)
watch(
  baseBottomGap,
  async () => {
    await nextTick();
    if (smartScroll.autoFollow.value) {
      smartScroll.followBottomSmooth();
    } else {
      smartScroll.syncVisibility();
    }
  },
  { flush: "post" },
);

onMounted(() => {
  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => {
      measureTurnSpacer();
      if (smartScroll.autoFollow.value && !smartScroll.isUserInteracting.value) {
        smartScroll.followBottomSmooth();
      } else {
        smartScroll.syncVisibility();
      }
    });
    if (scroller.value) resizeObserver.observe(scroller.value);
    if (wrapper.value) resizeObserver.observe(wrapper.value);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});

defineExpose({
  scrollToBottom,
  showJumpToBottom: smartScroll.showJumpToBottom,
  jumpToBottom: () => smartScroll.jumpToBottom("smooth"),
  scrollContainer: scroller,
});
</script>

<template>
  <div
    ref="scroller"
    tabindex="-1"
    class="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-4 pt-3 outline-none sm:px-6"
  >
    <!-- Empty State Matching Web Chat Centerpiece -->
    <div v-if="!visibleMessages.length" class="flex min-h-full flex-col items-center justify-center pb-36 pt-20 text-center">
      <div class="w-full max-w-2xl">
        <h2 class="text-[30px] font-semibold tracking-tight text-fg sm:text-[36px]">
          {{ projectName ? `在 ${projectName} 中协作` : "OpenCode 工作台" }}
        </h2>
        <p class="mx-auto mt-3 max-w-lg text-[15px] leading-relaxed text-fg-muted">
          使用 <code class="rounded-md bg-surface px-1.5 py-0.5 font-mono text-[12.5px]">@文件</code> 引用源码与子代理，
          <code class="rounded-md bg-surface px-1.5 py-0.5 font-mono text-[12.5px]">Tab</code> 切换 Build / Plan，
          <code class="rounded-md bg-surface px-1.5 py-0.5 font-mono text-[12.5px]">/</code> 调用指令与技能。
        </p>
      </div>
    </div>

    <div v-else ref="wrapper" class="relative mx-auto flex w-full max-w-4xl flex-col gap-5">
      <article
        v-for="(message, idx) in visibleMessages"
        :key="work.stableKeyOf(message.id)"
        :ref="(el) => setItemRef(idx, el as HTMLElement | null)"
        class="w-full"
        :class="message.role === 'user' ? 'group/user flex flex-col items-end' : 'group/assistant'"
      >
        <!-- User Message Bubble (Aligned with MessageBubble.vue) -->
        <template v-if="message.role === 'user'">
          <div class="flex max-w-[82%] flex-col items-end space-y-1.5">
            <div v-if="attachmentsOf(message).length" class="flex flex-wrap justify-end gap-1.5">
              <span
                v-for="(att, attIdx) in attachmentsOf(message)"
                :key="attIdx"
                class="rounded-xl bg-surface px-2.5 py-1 text-[11.5px] text-fg-muted"
              >
                {{ att.kind === "image" ? "🖼" : "📄" }} {{ att.name }}
              </span>
            </div>
            <div class="w-fit max-w-full rounded-[22px] bg-surface px-4 py-2.5 text-[15px] leading-relaxed text-fg">
              <div
                class="relative whitespace-pre-wrap break-words"
                :class="
                  isLongUserInput(message.content)
                    ? ['user-input-clamp', { 'is-expanded': isUserExpanded(message.id) }]
                    : ''
                "
              >
                {{ message.content }}
                <div
                  v-if="isLongUserInput(message.content) && !isUserExpanded(message.id)"
                  aria-hidden="true"
                  class="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-surface to-transparent"
                />
              </div>
              <div
                v-if="isLongUserInput(message.content)"
                class="mt-1.5 flex justify-end border-t border-line/45 pt-1.5"
              >
                <button
                  type="button"
                  class="focus-ring inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                  :aria-expanded="isUserExpanded(message.id)"
                  @click="toggleUserExpand(message.id)"
                >
                  <span>{{ isUserExpanded(message.id) ? "收起" : "展开全文" }}</span>
                  <svg
                    class="h-3.5 w-3.5 transition-transform duration-200"
                    :class="isUserExpanded(message.id) ? 'rotate-180' : ''"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    aria-hidden="true"
                  >
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6" />
                  </svg>
                </button>
              </div>
            </div>

            <div
              class="flex items-center justify-end gap-0.5 pt-0.5 opacity-0 transition-opacity duration-150 group-hover/user:opacity-100 focus-within:opacity-100"
            >
              <button
                type="button"
                class="focus-ring rounded-lg px-2 py-1 text-[11.5px] text-fg-faint transition-colors hover:bg-hover hover:text-fg disabled:opacity-40"
                :disabled="streaming"
                title="回退至此消息之前，并回滚之后的文件改动 (/undo)"
                @click="emit('revert', message.id)"
              >
                回退至此
              </button>
              <button
                type="button"
                class="focus-ring rounded-lg px-2 py-1 text-[11.5px] text-fg-faint transition-colors hover:bg-hover hover:text-fg"
                title="复制消息"
                @click="copyText(message.id, message.content)"
              >
                {{ copiedId === message.id ? "已复制" : "复制" }}
              </button>
            </div>
          </div>
        </template>

        <!-- Assistant Final Result (Main Area: Steps Pill + Final Output Only) -->
        <template v-else>
          <div class="min-w-0 space-y-2.5">
            <button
              v-if="stepCountOf(message) > 0 || isLiveMessage(message)"
              type="button"
              class="focus-ring inline-flex max-w-full items-center gap-2 rounded-full bg-surface px-3 py-1 text-[12px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
              :class="{ 'ring-1 ring-white/12 text-fg': selectedTurnId === message.id }"
              @click="emit('steps', message.id)"
            >
              <span
                class="h-1.5 w-1.5 shrink-0 rounded-full"
                :class="{ 'animate-pulse': isLiveMessage(message) }"
                :style="{ background: isLiveMessage(message) ? 'var(--work-accent)' : 'var(--success)' }"
              />
              <span class="truncate">{{ liveLabelOf(message) }}</span>
              <span v-if="stepCountOf(message) > 0" class="shrink-0 tabular-nums text-fg-faint">
                · {{ stepCountOf(message) }}
              </span>
              <svg class="h-3.5 w-3.5 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="m9 6 6 6-6 6" />
              </svg>
            </button>

            <div v-if="message.content" class="markdown-body">
              <MarkdownRenderer :content="message.content" :streaming="message.status === 'streaming'" />
            </div>
            <div
              v-else-if="message.status === 'streaming'"
              class="flex items-center gap-2 py-1.5 text-[13px] text-fg-faint"
              role="status"
              aria-live="polite"
            >
              <span class="inline-flex items-center gap-1" aria-hidden="true">
                <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent/80" />
                <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent/60 [animation-delay:150ms]" />
                <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-accent/40 [animation-delay:300ms]" />
              </span>
              <span>{{ liveLabelOf(message) }}</span>
            </div>
            <p v-else-if="message.status === 'waiting'" class="text-[12.5px] text-warning">等待你的确认后继续</p>
            <p v-else-if="message.status === 'failed'" class="text-[12.5px] text-danger">本轮执行失败</p>
            <p v-else-if="message.status === 'cancelled'" class="text-[12.5px] text-fg-faint">任务已停止</p>

            <!-- Hover Action Bar & Telemetry -->
            <div
              v-if="message.status !== 'streaming' && message.content"
              class="flex items-center gap-2 pt-0.5 text-[11.5px] text-fg-faint opacity-0 transition-opacity duration-150 group-hover/assistant:opacity-100 focus-within:opacity-100"
            >
              <button
                type="button"
                class="focus-ring rounded-lg px-2 py-1 transition-colors hover:bg-hover hover:text-fg"
                @click="copyText(message.id, message.content)"
              >
                {{ copiedId === message.id ? "已复制" : "复制" }}
              </button>
              <button
                type="button"
                class="focus-ring rounded-lg px-2 py-1 transition-colors hover:bg-hover hover:text-fg"
                title="从这条回答分叉一条独立新对话 (/fork)"
                @click="emit('fork', message.id)"
              >
                分支对话
              </button>
              <button
                v-if="desktop.loggedIn && desktop.online"
                type="button"
                class="focus-ring rounded-lg px-2 py-1 transition-colors hover:bg-hover hover:text-fg"
                title="将此结果带入 Whitz 云端 Chat 继续讨论"
                @click="emit('sendToChat', message.content)"
              >
                发往 Chat
              </button>
              <span v-if="usageOf(message)" class="ml-auto tabular-nums text-[11px] text-fg-faint">
                {{ formatTokens(usageOf(message)!.total) }} tokens
                <template v-if="usageOf(message)!.cost > 0">
                  · ${{ usageOf(message)!.cost.toFixed(4) }}
                </template>
              </span>
            </div>
          </div>
        </template>
      </article>

      <!-- Redo banner when messages were undone via /undo -->
      <div
        v-if="revertedCount && revertedCount > 0"
        class="mt-2 flex items-center justify-between rounded-2xl bg-surface/75 px-4 py-2 text-[12.5px] text-fg-muted"
      >
        <span>已撤回 {{ revertedCount }} 条消息及关联文件快照</span>
        <button
          type="button"
          class="font-medium text-accent transition-opacity hover:opacity-80"
          @click="emit('unrevert')"
        >
          重做恢复 (/redo)
        </button>
      </div>

      <div
        aria-hidden="true"
        class="shrink-0"
        :style="{ height: `${Math.round(baseBottomGap + extraTurnSpacer)}px` }"
      />
    </div>
  </div>
</template>
