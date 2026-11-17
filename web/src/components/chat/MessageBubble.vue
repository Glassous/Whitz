<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import type { Message } from "../../types";
import { useChatStore } from "../../stores/chat";
import { categoryLabel, formatFileSize } from "../../lib/fileTypes";
import MarkdownRenderer from "./MarkdownRenderer.vue";

const props = defineProps<{ message: Message }>();
const emit = defineEmits<{ steps: [] }>();
const chat = useChatStore();

const copied = ref(false);
let copyTimer: number | null = null;

async function copyContent() {
  const text = props.message.content;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
  copied.value = true;
  if (copyTimer) window.clearTimeout(copyTimer);
  copyTimer = window.setTimeout(() => {
    copied.value = false;
    copyTimer = null;
  }, 2000);
}

onBeforeUnmount(() => {
  if (copyTimer) window.clearTimeout(copyTimer);
});

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
    <div class="group/user flex max-w-[85%] flex-col items-end sm:max-w-[75%]">
      <div
        v-if="message.tool_payload?.attachments?.length"
        class="mb-1.5 flex flex-wrap justify-end gap-1.5"
      >
        <div
          v-for="att in message.tool_payload.attachments"
          :key="att.id"
          class="inline-flex max-w-[220px] items-center gap-1.5 rounded-xl bg-surface px-2.5 py-1 text-[12px] text-fg-muted"
          :title="`${att.filename} (${formatFileSize(att.size_bytes)})`"
        >
          <svg class="h-3.5 w-3.5 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M14 2v6h6" />
          </svg>
          <span class="truncate font-medium text-fg">{{ att.filename }}</span>
          <span class="shrink-0 text-[11px] text-fg-faint">{{ categoryLabel(att.category, att.ext) }}</span>
        </div>
      </div>
      <div
        class="w-fit max-w-full whitespace-pre-wrap rounded-[22px] bg-surface px-4 py-2.5 text-[15px] leading-relaxed text-fg"
      >
        {{ message.content }}
      </div>
      <div
        class="flex justify-end pt-1.5 transition-opacity duration-150"
        :class="
          copied
            ? 'pointer-events-auto opacity-100'
            : 'pointer-events-none opacity-0 group-hover/user:pointer-events-auto group-hover/user:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100'
        "
      >
        <button
          type="button"
          class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          :aria-label="copied ? '已复制' : '复制消息'"
          :title="copied ? '已复制' : '复制'"
          @click="copyContent"
        >
          <Transition
            mode="out-in"
            enter-active-class="transition duration-150 ease-out"
            enter-from-class="scale-75 opacity-0"
            enter-to-class="scale-100 opacity-100"
            leave-active-class="transition duration-100 ease-in"
            leave-from-class="scale-100 opacity-100"
            leave-to-class="scale-75 opacity-0"
          >
            <svg
              v-if="copied"
              key="check"
              class="h-4 w-4 text-success"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            <svg
              v-else
              key="copy"
              class="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
            >
              <rect x="9" y="9" width="11" height="11" rx="2.2" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
          </Transition>
        </button>
      </div>
    </div>
  </div>

  <div v-else class="min-w-0">
    <button
      type="button"
      class="mb-2.5 inline-flex min-h-8 max-w-full items-center gap-2 rounded-full px-3.5 py-1.5 text-[13px] font-medium transition-colors"
      :class="
        isCurrent
          ? 'bg-accent-weak/85 text-accent'
          : 'bg-surface/80 text-fg-muted hover:bg-surface hover:text-fg'
      "
      :aria-pressed="isCurrent"
      @click="emit('steps')"
    >
      <span class="truncate">{{ isLive ? liveLabel : "步骤查看" }}</span>
      <span v-if="!isLive && stepsCount" class="shrink-0 tabular-nums opacity-80">· {{ stepsCount }}</span>
      <svg class="h-3.5 w-3.5 shrink-0 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
      </svg>
    </button>

    <MarkdownRenderer :content="message.content" />
    <p v-if="message.status === 'failed'" class="mt-2 text-xs text-danger">回复失败，请重试。</p>
    <p v-else-if="message.status === 'cancelled'" class="mt-2 text-xs text-fg-faint">已停止生成</p>

    <div v-if="message.content.trim() && !isLive" class="mt-2 flex items-center">
      <button
        type="button"
        class="focus-ring flex h-7.5 w-7.5 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
        :aria-label="copied ? '已复制' : '复制回复'"
        :title="copied ? '已复制' : '复制'"
        @click="copyContent"
      >
        <Transition
          mode="out-in"
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="scale-75 opacity-0"
          enter-to-class="scale-100 opacity-100"
          leave-active-class="transition duration-100 ease-in"
          leave-from-class="scale-100 opacity-100"
          leave-to-class="scale-75 opacity-0"
        >
          <svg
            v-if="copied"
            key="check"
            class="h-4 w-4 text-success"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          <svg
            v-else
            key="copy"
            class="h-4 w-4"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.85"
          >
            <rect x="9" y="9" width="11" height="11" rx="2.2" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
        </Transition>
      </button>
    </div>
  </div>
</template>
