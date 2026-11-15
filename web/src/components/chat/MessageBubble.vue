<script setup lang="ts">
import { computed } from "vue";
import type { Message } from "../../types";
import { useChatStore } from "../../stores/chat";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const props = defineProps<{ message: Message }>();
const emit = defineEmits<{ steps: [] }>();
const chat = useChatStore();

const isCurrent = computed(() => chat.selectedTurn?.id === props.message.id);

const isLive = computed(() => chat.streaming && chat.activeAssistantId === props.message.id);

const liveLabel = computed(() => {
  if (chat.currentStep) {
    const step = chat.currentStep;
    return step.title ? `步骤 ${step.index}/${step.total} · ${step.title}` : `步骤 ${step.index}/${step.total}`;
  }
  if (chat.runningTool) return `正在使用 ${chat.runningTool}`;
  const items = chat.plan?.items ?? [];
  if (items.length && items.every((item) => item.status === "completed")) return "正在生成回答…";
  return "正在思考…";
});

const stepsCount = computed(() => {
  const plan = isCurrent.value ? chat.viewPlan : props.message.tool_payload?.plan;
  if (plan?.items?.length) return plan.items.length;
  const blocks = isCurrent.value ? chat.viewReasoning : props.message.tool_payload?.reasoning ?? [];
  const keys = new Set(
    blocks.filter((b) => b.step != null).map((b) => b.step_id ?? `step-${b.step}`),
  );
  return keys.size;
});
</script>

<template>
  <div v-if="message.role === 'user'" class="flex justify-end">
    <div
      class="max-w-[85%] whitespace-pre-wrap rounded-[22px] bg-surface px-4 py-2.5 text-[15px] leading-relaxed text-fg sm:max-w-[75%]"
    >
      {{ message.content }}
    </div>
  </div>

  <div v-else class="flex gap-3">
    <div class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-fg">
      W
    </div>
    <div class="min-w-0 flex-1 pt-0.5">
      <button
        type="button"
        class="mb-2 inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors"
        :class="
          isCurrent
            ? 'border-accent/45 bg-accent-weak/50 text-accent'
            : 'border-line bg-canvas/60 text-fg-faint hover:border-line-strong hover:text-fg-muted'
        "
        :aria-pressed="isCurrent"
        @click="emit('steps')"
      >
        <span class="truncate">{{ isLive ? liveLabel : "步骤查看" }}</span>
        <span v-if="!isLive && stepsCount" class="shrink-0 tabular-nums opacity-80">· {{ stepsCount }}</span>
        <svg class="h-2.5 w-2.5 shrink-0 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
        </svg>
      </button>
      <MarkdownRenderer :content="message.content" />
      <p v-if="message.status === 'failed'" class="mt-2 text-xs text-danger">回复失败，请重试。</p>
      <p v-else-if="message.status === 'cancelled'" class="mt-2 text-xs text-fg-faint">已停止生成</p>
    </div>
  </div>
</template>
