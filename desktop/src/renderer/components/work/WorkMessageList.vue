<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkMessage } from "@shared/work-types";
import MarkdownRenderer from "@web/components/chat/MarkdownRenderer.vue";

const props = defineProps<{
  messages: WorkMessage[];
  activeAssistantId: string | null;
  streaming: boolean;
}>();

const emit = defineEmits<{
  openFile: [string];
}>();

const scroller = ref<HTMLElement | null>(null);
const blocks = computed(() => props.messages);

function reasoningOf(message: WorkMessage): Array<Record<string, unknown>> {
  const value = message.tool_payload?.reasoning;
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function attachmentsOf(message: WorkMessage): Array<{ name: string; kind: string }> {
  const value = message.tool_payload?.attachments;
  return Array.isArray(value) ? (value as Array<{ name: string; kind: string }>) : [];
}

function toolDisplayLabel(name: string | null): string {
  const map: Record<string, string> = {
    read: "读取文件",
    read_file: "读取文件",
    write: "写入文件",
    write_file: "写入文件",
    edit: "编辑文件",
    multiedit: "批量编辑",
    apply_patch: "应用补丁",
    patch: "修改补丁",
    glob: "文件匹配",
    grep: "全文搜索",
    list: "目录浏览",
    search_files: "搜索工作区",
    bash: "终端命令",
    terminal: "终端命令",
    execute_code: "代码执行",
    webfetch: "抓取网页",
    websearch: "网页检索",
    web_search: "网页检索",
    web_extract: "网页提取",
    todowrite: "任务计划",
    todo_list: "任务计划",
    task: "子任务委派",
    skill: "读取技能",
  };
  return (name && map[name]) || name || "工具调用";
}

function extractFilePath(message: WorkMessage): string | null {
  const tool = message.tool_name ?? "";
  if (!["read", "write", "edit", "read_file", "write_file", "patch"].includes(tool)) return null;
  const rawArgs = message.tool_payload?.args;
  if (!rawArgs) return null;
  if (typeof rawArgs === "object" && !Array.isArray(rawArgs)) {
    const obj = rawArgs as Record<string, unknown>;
    const p = obj.filePath ?? obj.path ?? obj.file_path ?? obj.target_file;
    if (typeof p === "string" && p.trim()) return p.trim();
  }
  const raw = typeof rawArgs === "string" ? rawArgs : JSON.stringify(rawArgs);
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const p = parsed.filePath ?? parsed.path ?? parsed.file_path ?? parsed.target_file;
    if (typeof p === "string" && p.trim()) return p.trim();
  } catch {
    const match = /["']?([a-zA-Z0-9_.\-\\/]+\.[a-zA-Z0-9]+)["']?/.exec(raw);
    if (match) return match[1];
  }
  return null;
}

function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function toolSummary(message: WorkMessage): string {
  const args = message.tool_payload?.args;
  if (!args) return "";
  const text = typeof args === "string" ? args : JSON.stringify(args);
  return text.replace(/\s+/g, " ").slice(0, 90);
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
  <div ref="scroller" class="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-5 py-5 sm:px-6">
    <article
      v-for="message in blocks"
      :key="message.id"
      class="mx-auto mb-4 max-w-[860px]"
      :class="message.role === 'user' ? 'flex justify-end' : ''"
    >
      <template v-if="message.role === 'user'">
        <div class="max-w-[78%] space-y-1.5">
          <div v-if="attachmentsOf(message).length" class="flex flex-wrap justify-end gap-1.5">
            <span
              v-for="(att, idx) in attachmentsOf(message)"
              :key="idx"
              class="rounded-lg border border-line bg-surface px-2 py-0.5 text-[11px] text-fg-muted"
            >
              {{ att.kind === "image" ? "🖼" : "📄" }} {{ att.name }}
            </span>
          </div>
          <div class="rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap text-primary-fg shadow-sm">
            {{ message.content }}
          </div>
        </div>
      </template>

      <template v-else-if="message.role === 'tool'">
        <details
          class="disclosure-card rounded-xl border border-line bg-surface/45 text-[12px]"
          :open="message.status === 'running' || message.status === 'failed'"
        >
          <summary class="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2 select-none">
            <span
              class="h-1.5 w-1.5 shrink-0 rounded-full"
              :class="{ 'animate-pulse': message.status === 'running' }"
              :style="{
                background:
                  message.status === 'running'
                    ? 'var(--warning)'
                    : message.status === 'failed'
                      ? 'var(--danger)'
                      : 'var(--success)',
              }"
            ></span>
            <span class="shrink-0 font-medium text-fg">{{ toolDisplayLabel(message.tool_name) }}</span>
            <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-faint">
              {{ extractFilePath(message) || toolSummary(message) }}
            </span>
            <button
              v-if="extractFilePath(message)"
              type="button"
              class="shrink-0 rounded-md border border-line bg-canvas px-1.5 py-0.5 text-[10.5px] text-fg-muted hover:text-fg"
              @click.stop.prevent="emit('openFile', extractFilePath(message)!)"
            >
              预览
            </button>
            <span v-if="message.tool_payload?.duration" class="shrink-0 text-[11px] text-fg-faint">
              {{ Number(message.tool_payload.duration).toFixed(1) }}s
            </span>
          </summary>

          <div class="space-y-2 border-t border-line/70 px-3.5 py-2.5">
            <pre
              v-if="message.tool_payload?.args"
              class="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-code px-2.5 py-2 font-mono text-[11px] leading-relaxed text-[#c6c5be]"
            >{{ formatPayloadValue(message.tool_payload.args) }}</pre>
            <pre
              v-if="message.tool_payload?.result || message.tool_payload?.error"
              class="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-code px-2.5 py-2 font-mono text-[11px] leading-relaxed"
              :class="message.status === 'failed' ? 'text-[#f3a6a0]' : 'text-[#d6d5ce]'"
            >{{ formatPayloadValue(message.tool_payload?.error ?? message.tool_payload?.result ?? "") }}</pre>
          </div>
        </details>
      </template>

      <template v-else>
        <div class="flex items-start gap-2.5">
          <span
            class="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-canvas text-[11px] font-semibold"
            style="color: var(--work-accent)"
          >
            O
          </span>
          <div class="min-w-0 flex-1">
            <details v-if="reasoningOf(message).length" class="disclosure-card mb-2 rounded-xl border border-line bg-surface/40">
              <summary class="flex cursor-pointer items-center gap-2 px-3 py-2 text-[12px] text-fg-muted">
                <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)"></span>
                思考与中间过程 · {{ reasoningOf(message).length }} 段
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
              OpenCode 正在思考与调度工具…
            </p>
            <p v-if="message.status === 'waiting'" class="mt-2 text-[12px] text-warning">等待你的确认后继续</p>
            <p v-if="message.status === 'failed'" class="mt-2 text-[12px] text-danger">本轮执行失败</p>
          </div>
        </div>
      </template>
    </article>

    <div v-if="!blocks.length" class="mx-auto mt-14 max-w-[520px] rounded-2xl border border-line/80 bg-surface/35 p-6 text-center">
      <p class="text-[14px] font-medium text-fg">本地 OpenCode 工作台已就绪</p>
      <p class="mt-2 text-[12.5px] leading-relaxed text-fg-muted">
        可以直接让它分析当前工作区代码、编写新功能、重构文件、执行终端命令与测试，支持 <code class="rounded bg-surface px-1 py-0.5 text-[11px]">@文件</code> 引用工作区源码。
      </p>
      <p class="mt-2 text-[11.5px] text-fg-faint">
        所有本地对话与工作区记录只写入这台电脑的 SQLite，不与云端 Chat 混合。
      </p>
    </div>
  </div>
</template>
