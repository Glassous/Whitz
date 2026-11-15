<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import type { Message } from "../../types";
import MessageBubble from "./MessageBubble.vue";

const props = defineProps<{ messages: Message[] }>();
const emit = defineEmits<{ steps: [id: string] }>();
const container = ref<HTMLElement | null>(null);

const visibleMessages = computed(() => props.messages.filter((m) => m.role !== "tool"));

function nearBottom(): boolean {
  const el = container.value;
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
}

function scrollToBottom() {
  const el = container.value;
  if (el) el.scrollTop = el.scrollHeight;
}

const scrollSignature = () => {
  const last = visibleMessages.value[visibleMessages.value.length - 1];
  return `${visibleMessages.value.length}:${last?.content.length ?? 0}:${last?.status ?? ""}`;
};

watch(
  scrollSignature,
  async () => {
    const shouldFollow = nearBottom();
    await nextTick();
    if (shouldFollow) scrollToBottom();
  },
  { flush: "post" },
);

watch(
  () => visibleMessages.value.length,
  async () => {
    await nextTick();
    scrollToBottom();
  },
);

onMounted(async () => {
  await nextTick();
  scrollToBottom();
});
</script>

<template>
  <div ref="container" class="h-full overflow-y-auto">
    <div class="mx-auto w-full max-w-3xl space-y-5 px-4 pb-8 pt-6 sm:px-6 sm:pt-8">
      <MessageBubble v-for="m in visibleMessages" :key="m.id" :message="m" @steps="emit('steps', m.id)" />
    </div>
  </div>
</template>
