<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onBeforeUpdate, onMounted, ref, watch } from "vue";
import type { ConversationFile, DeliverableTarget, Message } from "../../types";
import { useChatStore } from "../../stores/chat";
import { useSmartStreamScroll } from "../../composables/useSmartStreamScroll";
import MessageBubble from "./MessageBubble.vue";

const props = defineProps<{
  messages: Message[];
  focusMessageId?: string | null;
  downloadingFileId?: string | null;
  bottomInset?: number;
}>();
const emit = defineEmits<{
  steps: [id: string];
  "focus-handled": [];
  regenerate: [assistantMessageId: string];
  edit: [userMessageId: string, content: string];
  "preview-html": [html: string];
  "preview-file": [file: ConversationFile];
  "open-deliverable": [target: DeliverableTarget];
  "open-lightbox": [file: ConversationFile, siblings: ConversationFile[]];
  "download-file": [file: ConversationFile];
}>();

const TOP_CLEARANCE = 88;
const DEFAULT_BOTTOM_GAP = 148;

const chat = useChatStore();
const container = ref<HTMLElement | null>(null);
const wrapper = ref<HTMLElement | null>(null);
const itemRefs = ref<(HTMLElement | null)[]>([]);
const baseBottomGap = computed(() => Math.max(DEFAULT_BOTTOM_GAP, (props.bottomInset ?? 0) + 20));
const extraTurnSpacer = ref(0);
const highlightedId = ref<string | null>(null);

let turnRevealActive = false;
let turnRevealInitialized = false;
let resizeObserver: ResizeObserver | null = null;
let highlightTimer: number | null = null;

const smartScroll = useSmartStreamScroll(container);

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

function measureTurnSpacer(): { el: HTMLElement; targetTop: number } | null {
  const el = container.value;
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

async function scrollToMessage(id: string) {
  smartScroll.disengage();
  turnRevealActive = false;
  await nextTick();
  const el = container.value;
  const idx = visibleMessages.value.findIndex((m) => m.id === id);
  const targetEl = idx >= 0 ? itemRefs.value[idx] : null;
  if (!el || !targetEl) {
    smartScroll.jumpToBottom("instant");
    return;
  }
  const usableHeight = Math.max(0, el.clientHeight - TOP_CLEARANCE - baseBottomGap.value);
  const lastEl = itemRefs.value[visibleMessages.value.length - 1];
  const contentFromTarget = lastEl ? Math.max(0, lastEl.offsetTop + lastEl.offsetHeight - targetEl.offsetTop) : 0;
  const neededExtra = Math.max(0, usableHeight - contentFromTarget);
  if (neededExtra > extraTurnSpacer.value) {
    extraTurnSpacer.value = neededExtra;
    await nextTick();
  }
  smartScroll.scrollToTopPosition(Math.max(0, targetEl.offsetTop - TOP_CLEARANCE));
  highlightedId.value = id;
  if (highlightTimer) window.clearTimeout(highlightTimer);
  highlightTimer = window.setTimeout(() => {
    highlightedId.value = null;
    highlightTimer = null;
  }, 1800);
  emit("focus-handled");
}

// Switch conversation -> reset turn spacer and land cleanly at bottom
watch(
  () => chat.convId,
  async () => {
    turnRevealActive = false;
    turnRevealInitialized = false;
    extraTurnSpacer.value = 0;
    await nextTick();
    if (!props.focusMessageId) {
      smartScroll.jumpToBottom("instant");
    }
  },
);

// Explicit new turn (send / regenerate / edit-resend) -> Top-anchored turn reveal
watch(
  () => chat.latestTurnTriggerSeq,
  async (seq) => {
    if (seq > 0) {
      await scrollToLatestTurnTop();
    }
  },
);

// Streaming growth -> monotonically shrink spacer, then smoothly follow bottom if user didn't scroll away
const streamSignature = computed(() => {
  const last = visibleMessages.value[visibleMessages.value.length - 1];
  return `${visibleMessages.value.length}:${last?.content.length ?? 0}:${last?.status ?? ""}`;
});

watch(
  streamSignature,
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

// Bottom overlay height change (ApprovalCard / ClarifyCard / multi-line composer) -> keep bottom clear
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

watch(
  () => props.focusMessageId,
  (id) => {
    if (id) void scrollToMessage(id);
  },
);

onMounted(async () => {
  if (props.focusMessageId) {
    await scrollToMessage(props.focusMessageId);
  } else {
    await nextTick();
    smartScroll.jumpToBottom("instant");
  }
  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => {
      measureTurnSpacer();
      if (smartScroll.autoFollow.value && !smartScroll.isUserInteracting.value) {
        smartScroll.followBottomSmooth();
      } else {
        smartScroll.syncVisibility();
      }
    });
    if (container.value) resizeObserver.observe(container.value);
    if (wrapper.value) resizeObserver.observe(wrapper.value);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
  if (highlightTimer) window.clearTimeout(highlightTimer);
});

defineExpose({
  showJumpToBottom: smartScroll.showJumpToBottom,
  jumpToBottom: () => smartScroll.jumpToBottom("smooth"),
  scrollContainer: container,
});
</script>

<template>
  <div ref="container" v-scrollbar tabindex="-1" class="custom-scrollbar h-full overflow-y-auto outline-none">
    <div ref="wrapper" class="relative mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 pt-[88px] sm:px-6">
      <div
        v-for="(m, idx) in visibleMessages"
        :key="chat.stableKeyOf(m.id)"
        :ref="(el) => setItemRef(idx, el as HTMLElement | null)"
        class="-mx-2 rounded-2xl px-2 py-1 transition-colors duration-700"
        :class="[
          highlightedId === m.id ? 'bg-accent-weak/75' : '',
          idx < visibleMessages.length - 6 ? 'message-deferred' : '',
        ]"
      >
        <MessageBubble
          :message="m"
          :downloading-file-id="downloadingFileId"
          @steps="emit('steps', m.id)"
          @regenerate="emit('regenerate', $event)"
          @edit="(id, content) => emit('edit', id, content)"
          @preview-html="emit('preview-html', $event)"
          @preview-file="emit('preview-file', $event)"
          @open-deliverable="emit('open-deliverable', $event)"
          @open-lightbox="(f, list) => emit('open-lightbox', f, list)"
          @download-file="emit('download-file', $event)"
        />
      </div>
      <div
        aria-hidden="true"
        class="shrink-0"
        :style="{ height: `${Math.round(baseBottomGap + extraTurnSpacer)}px` }"
      />
    </div>
  </div>
</template>
