<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkMessage, WorkTokenUsage } from "@shared/work-types";
import { useWorkStore } from "../../stores/work";
import MarkdownRenderer from "@web/components/chat/MarkdownRenderer.vue";

const NEAR_BOTTOM_PX = 120;

const props = defineProps<{
  conversationId: string | null;
  messages: WorkMessage[];
  activeAssistantId: string | null;
  selectedTurnId: string | null;
  streaming: boolean;
  revertedCount?: number;
  projectName?: string | null;
}>();

const emit = defineEmits<{
  openFile: [string];
  revert: [string];
  unrevert: [];
  fork: [string];
  steps: [string];
}>();

const work = useWorkStore();
const scroller = ref<HTMLElement | null>(null);
const copiedId = ref<string | null>(null);
const expandedUserIds = ref<Set<string>>(new Set());
const autoFollow = ref(true);
let programmaticUntil = 0;

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

function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
}

function onScrollerScroll() {
  const el = scroller.value;
  if (!el) return;
  if (performance.now() < programmaticUntil) return;
  autoFollow.value = isNearBottom(el);
}

function onScrollerWheel(e: WheelEvent) {
  if (e.deltaY < 0) {
    autoFollow.value = false;
  }
}

function scrollToBottom(force = false) {
  if (force) autoFollow.value = true;
  if (!autoFollow.value) return;
  void nextTick(() => {
    const el = scroller.value;
    if (!el || (!force && !autoFollow.value)) return;
    programmaticUntil = performance.now() + 45;
    el.scrollTop = el.scrollHeight;
  });
}

watch(
  () => props.conversationId,
  () => {
    autoFollow.value = true;
    scrollToBottom(true);
  },
  { immediate: true },
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
  ([len], prev) => {
    const last = visibleMessages.value[len - 1];
    if (prev && len > prev[0] && last?.role === "user") {
      scrollToBottom(true);
      return;
    }
    scrollToBottom(false);
  },
  { flush: "post" },
);

defineExpose({ scrollToBottom });
</script>

<template>
  <div
    ref="scroller"
    class="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-4 pb-44 pt-3 sm:px-6"
    @scroll.passive="onScrollerScroll"
    @wheel.passive="onScrollerWheel"
  >
    <!-- Empty State Matching Web Chat Centerpiece -->
    <div v-if="!visibleMessages.length" class="flex min-h-full flex-col items-center justify-center py-20 text-center">
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

    <template v-else>
      <article
        v-for="message in visibleMessages"
        :key="message.id"
        class="mx-auto mb-5 max-w-4xl"
        :class="message.role === 'user' ? 'group/user flex flex-col items-end' : 'group/assistant'"
      >
        <!-- User Message Bubble (Aligned with MessageBubble.vue) -->
        <template v-if="message.role === 'user'">
          <div class="flex max-w-[82%] flex-col items-end space-y-1.5">
            <div v-if="attachmentsOf(message).length" class="flex flex-wrap justify-end gap-1.5">
              <span
                v-for="(att, idx) in attachmentsOf(message)"
                :key="idx"
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
              <MarkdownRenderer :content="message.content" />
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
        class="mx-auto mt-2 flex max-w-4xl items-center justify-between rounded-2xl bg-surface/75 px-4 py-2 text-[12.5px] text-fg-muted"
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
    </template>
  </div>
</template>
