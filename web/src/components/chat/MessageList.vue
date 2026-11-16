<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onBeforeUpdate, onMounted, ref, watch } from "vue";
import type { Message } from "../../types";
import MessageBubble from "./MessageBubble.vue";

const props = defineProps<{ messages: Message[] }>();
const emit = defineEmits<{ steps: [id: string] }>();

const TOP_CLEARANCE = 88;
const MIN_BOTTOM_GAP = 32;

const container = ref<HTMLElement | null>(null);
const wrapper = ref<HTMLElement | null>(null);
const itemRefs = ref<(HTMLElement | null)[]>([]);
const spacerHeight = ref(MIN_BOTTOM_GAP);

let resizeObserver: ResizeObserver | null = null;

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

function measureLatestTurn(): { el: HTMLElement; targetTop: number } | null {
  const el = container.value;
  const idx = latestTurnStartIndex.value;
  const startEl = idx >= 0 ? itemRefs.value[idx] : null;
  const lastEl = itemRefs.value[visibleMessages.value.length - 1];
  if (!el || !startEl || !lastEl) {
    spacerHeight.value = MIN_BOTTOM_GAP;
    return null;
  }
  const targetTop = startEl.offsetTop;
  const contentBottom = lastEl.offsetTop + lastEl.offsetHeight;
  const latestTurnHeight = Math.max(0, contentBottom - targetTop);
  const neededFromTarget = Math.max(0, el.clientHeight - TOP_CLEARANCE);
  const nextSpacer = Math.max(MIN_BOTTOM_GAP, neededFromTarget - latestTurnHeight);
  if (Math.abs(spacerHeight.value - nextSpacer) > 0.5) {
    spacerHeight.value = nextSpacer;
  }
  return { el, targetTop };
}

function nearBottom(): boolean {
  const el = container.value;
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
}

function scrollToBottom() {
  const el = container.value;
  if (el) el.scrollTop = el.scrollHeight;
}

async function scrollToLatestTurnTop() {
  await nextTick();
  const measured = measureLatestTurn();
  await nextTick();
  if (!measured) return;
  measured.el.scrollTop = Math.max(0, measured.targetTop - TOP_CLEARANCE);
}

const scrollSignature = () => {
  const last = visibleMessages.value[visibleMessages.value.length - 1];
  return `${visibleMessages.value.length}:${last?.content.length ?? 0}:${last?.status ?? ""}`;
};

let lastLength = visibleMessages.value.length;

watch(
  scrollSignature,
  async () => {
    const currentLength = visibleMessages.value.length;
    if (currentLength !== lastLength) {
      lastLength = currentLength;
      return;
    }
    const shouldFollow = nearBottom();
    await nextTick();
    measureLatestTurn();
    await nextTick();
    if (shouldFollow) scrollToBottom();
  },
  { flush: "post" },
);

watch(
  () => visibleMessages.value.length,
  async () => {
    await scrollToLatestTurnTop();
  },
);

onMounted(async () => {
  await scrollToLatestTurnTop();
  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => {
      measureLatestTurn();
    });
    if (container.value) resizeObserver.observe(container.value);
    if (wrapper.value) resizeObserver.observe(wrapper.value);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});
</script>

<template>
  <div ref="container" v-scrollbar class="custom-scrollbar h-full overflow-y-auto">
    <div ref="wrapper" class="relative mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 pt-[88px] sm:px-6">
      <div
        v-for="(m, idx) in visibleMessages"
        :key="m.id"
        :ref="(el) => setItemRef(idx, el as HTMLElement | null)"
      >
        <MessageBubble :message="m" @steps="emit('steps', m.id)" />
      </div>
      <div aria-hidden="true" class="shrink-0" :style="{ height: `${spacerHeight}px` }" />
    </div>
  </div>
</template>
