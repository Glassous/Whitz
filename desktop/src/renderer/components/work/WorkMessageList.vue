<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkMessage } from "@shared/work-types";
import MarkdownRenderer from "@web/components/chat/MarkdownRenderer.vue";

const props = defineProps<{
  messages: WorkMessage[];
  activeAssistantId: string | null;
  streaming: boolean;
}>();

const scroller = ref<HTMLElement | null>(null);

const blocks = computed(() => props.messages);

function reasoningOf(message: WorkMessage): Array<Record<string, unknown>> {
  const value = message.tool_payload?.reasoning;
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function scrollToBottom(smooth = false) {
  void nextTick(() => {
    const element = scroller.value;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  });
}

watch(
  () => [props.messages.length, props.messages.map((m) => m.content.length).join(","), props.streaming],
  () => scrollToBottom(true),
);

defineExpose({ scrollToBottom });
</script>

<template>
  <div ref="scroller" class="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-6 py-5">
    <article
      v-for="message in blocks"
      :key="message.id"
      class="mx-auto mb-5 max-w-[860px]"
      :class="message.role === 'user' ? 'flex justify-end' : ''"
    >
      <template v-if="message.role === 'user'">
        <div class="max-w-[76%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14px] leading-relaxed text-primary-fg shadow-sm">
          {{ message.content }}
        </div>
      </template>

      <template v-else-if="message.role === 'tool'">
        <div class="rounded-xl border border-line bg-surface/50 px-3.5 py-2.5">
          <div class="flex items-center gap-2 text-[12px]">
            <span
              class="h-1.5 w-1.5 rounded-full"
              :style="{
                background:
                  message.status === 'running'
                    ? 'var(--warning)'
                    : message.status === 'failed'
                      ? 'var(--danger)'
                      : 'var(--success)',
              }"
            ></span>
            <span class="font-medium text-fg">{{ message.tool_name }}</span>
            <span class="text-fg-faint">{{ message.status }}</span>
            <span v-if="message.tool_payload?.duration" class="text-fg-faint">
              · {{ Number(message.tool_payload.duration).toFixed(1) }}s
            </span>
          </div>
          <pre
            v-if="message.tool_payload?.result || message.tool_payload?.args"
            class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-code px-2.5 py-2 font-mono text-[11px] leading-relaxed text-[#d6d5ce]"
          >{{ String(message.tool_payload?.result ?? message.tool_payload?.args ?? "") }}</pre>
        </div>
      </template>

      <template v-else>
        <div class="flex items-start gap-2.5">
          <span class="mt-1 h-5 w-5 shrink-0 rounded-full border border-line bg-canvas text-center text-[10px] leading-[18px] text-fg-faint">
            W
          </span>
          <div class="min-w-0 flex-1">
            <details v-if="reasoningOf(message).length" class="disclosure-card mb-2 rounded-xl border border-line bg-surface/40">
              <summary class="flex cursor-pointer items-center gap-2 px-3 py-2 text-[12px] text-fg-muted">
                <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)"></span>
                思考过程 · {{ reasoningOf(message).length }} 段
              </summary>
              <div class="space-y-2 border-t border-line px-3 py-2.5">
                <div v-for="(block, index) in reasoningOf(message)" :key="index" class="text-[12.5px] leading-relaxed text-fg-muted">
                  <p v-if="block.title" class="mb-1 text-[11px] font-medium text-fg-faint">{{ block.title }}</p>
                  <p v-if="block.text" class="whitespace-pre-wrap">{{ block.text }}</p>
                  <p v-if="block.content" class="mt-1 whitespace-pre-wrap">{{ block.content }}</p>
                </div>
              </div>
            </details>

            <div v-if="message.content" class="markdown-body">
              <MarkdownRenderer :content="message.content" />
            </div>
            <p v-else-if="message.status === 'streaming'" class="flex items-center gap-2 text-[13px] text-fg-faint">
              <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full" style="background: var(--work-accent)"></span>
              正在思考…
            </p>
            <p v-if="message.status === 'waiting'" class="mt-2 text-[12px] text-warning">等待你的确认</p>
            <p v-if="message.status === 'failed'" class="mt-2 text-[12px] text-danger">本轮执行失败</p>
          </div>
        </div>
      </template>
    </article>

    <p v-if="!blocks.length" class="mx-auto mt-16 max-w-[420px] text-center text-[13px] leading-relaxed text-fg-faint">
      本地智能体已就绪。它可以读取本机文件、运行命令、访问网页——
      <br />
      所有记录只写入这台电脑的 SQLite，不会上传。
    </p>
  </div>
</template>
