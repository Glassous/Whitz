<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { WorkMessage, WorkTokenUsage } from "@shared/work-types";
import MarkdownRenderer from "@web/components/chat/MarkdownRenderer.vue";

const props = defineProps<{
  messages: WorkMessage[];
  activeAssistantId: string | null;
  streaming: boolean;
  revertedCount?: number;
  projectName?: string | null;
}>();

const emit = defineEmits<{
  openFile: [string];
  revert: [string];
  unrevert: [];
  fork: [string];
}>();

const scroller = ref<HTMLElement | null>(null);
const copiedId = ref<string | null>(null);
const blocks = computed(() => props.messages);

function reasoningOf(message: WorkMessage): Array<Record<string, unknown>> {
  const value = message.tool_payload?.reasoning;
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
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
  <div ref="scroller" class="min-h-0 flex-1 overflow-y-auto custom-scrollbar px-4 pb-44 pt-3 sm:px-6">
    <!-- Empty State Matching Web Chat Centerpiece -->
    <div v-if="!blocks.length" class="flex min-h-full flex-col items-center justify-center py-20 text-center">
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
        v-for="message in blocks"
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
            <div class="w-fit max-w-full whitespace-pre-wrap rounded-[22px] bg-surface px-4 py-2.5 text-[15px] leading-relaxed text-fg">
              {{ message.content }}
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

        <!-- Tool Call Pill (Borderless tonal card) -->
        <template v-else-if="message.role === 'tool'">
          <details
            class="disclosure-card rounded-2xl bg-surface/60 text-[12.5px]"
            :open="message.status === 'running' || message.status === 'failed'"
          >
            <summary class="flex cursor-pointer list-none items-center gap-2.5 px-3.5 py-2 select-none">
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
              />
              <span class="shrink-0 font-medium text-fg">{{ toolDisplayLabel(message.tool_name) }}</span>
              <span class="min-w-0 flex-1 truncate font-mono text-[11.5px] text-fg-faint">
                {{ extractFilePath(message) || toolSummary(message) }}
              </span>
              <button
                v-if="extractFilePath(message)"
                type="button"
                class="shrink-0 rounded-lg bg-canvas/85 px-2 py-0.5 text-[11px] text-fg-muted transition-colors hover:text-fg"
                @click.stop.prevent="emit('openFile', extractFilePath(message)!)"
              >
                预览
              </button>
              <span v-if="message.tool_payload?.duration" class="shrink-0 text-[11px] tabular-nums text-fg-faint">
                {{ Number(message.tool_payload.duration).toFixed(1) }}s
              </span>
            </summary>

            <div class="space-y-2 px-3.5 pb-3 pt-1">
              <pre
                v-if="message.tool_payload?.args"
                class="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code px-3 py-2 font-mono text-[11.5px] leading-relaxed text-[#c6c5be]"
              >{{ formatPayloadValue(message.tool_payload.args) }}</pre>
              <pre
                v-if="message.tool_payload?.result || message.tool_payload?.error"
                class="max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code px-3 py-2 font-mono text-[11.5px] leading-relaxed"
                :class="message.status === 'failed' ? 'text-[#f3a6a0]' : 'text-[#d6d5ce]'"
              >{{ formatPayloadValue(message.tool_payload?.error ?? message.tool_payload?.result ?? "") }}</pre>
            </div>
          </details>
        </template>

        <!-- Assistant Prose (Clean full-width layout aligned with MessageBubble.vue) -->
        <template v-else>
          <div class="min-w-0 space-y-2">
            <details v-if="reasoningOf(message).length" class="disclosure-card inline-block max-w-full rounded-2xl bg-surface/60">
              <summary class="flex cursor-pointer list-none items-center gap-2 px-3.5 py-1.5 text-[12.5px] text-fg-muted select-none">
                <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)" />
                <span>思考过程 · {{ reasoningOf(message).length }} 段</span>
              </summary>
              <div class="space-y-2 px-3.5 pb-3 pt-1">
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
            <p v-else-if="message.status === 'streaming'" class="flex items-center gap-2 text-[13.5px] text-fg-faint">
              <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full" style="background: var(--work-accent)" />
              正在思考与调度工具…
            </p>
            <p v-if="message.status === 'waiting'" class="text-[12.5px] text-warning">等待你的确认后继续</p>
            <p v-if="message.status === 'failed'" class="text-[12.5px] text-danger">本轮执行失败</p>

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
