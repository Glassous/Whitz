<script setup lang="ts">
import { computed, ref } from "vue";
import type { ReasoningBlock, ReasoningTool } from "../../types";

const props = defineProps<{ block: ReasoningBlock }>();

const textOpen = ref(false);
const contentOpen = ref(false);
const openTools = ref<Set<number>>(new Set());

const longText = computed(() => {
  const text = props.block.text;
  return text.length > 180 || text.split("\n").filter((line) => line.trim()).length > 3;
});

const longContent = computed(() => {
  const text = props.block.content ?? "";
  return text.length > 180 || text.split("\n").filter((line) => line.trim()).length > 3;
});

function toggleTool(index: number) {
  const next = new Set(openTools.value);
  if (next.has(index)) next.delete(index);
  else next.add(index);
  openTools.value = next;
}

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  in_progress: "进行中",
  pending: "待执行",
};

const TOOL_LABELS: Record<string, string> = {
  todo_list: "更新任务清单",
  tool_search: "检索工具",
  tool_describe: "查看工具说明",
  skill_view: "查看技能",
  web_search: "联网搜索",
  web_extract: "读取网页",
  memory: "记忆",
  skill: "技能",
  rag_search_workspace: "检索工作区",
  memory_search: "RAG 检索记忆集",
  memory_list: "查看记忆集",
  memory_propose: "写入/修改记忆",
  memory_manage_collection: "管理记忆集",
  clarify: "向用户澄清",
  execute_code: "沙盒代码执行",
  delegate_subtask: "子智能体协作",
  request_deep_thinking: "开启深度思考",
  list_workspace_files: "查看工作区文件",
  read_workspace_file: "读取工作区文件",
  search_workspace_files: "检索工作区文件",
  write_workspace_file: "写入工作区文件",
  list_user_skills: "查看可用技能",
  preview_github_skill: "预览 GitHub 技能",
  install_github_skill: "安装 GitHub 技能",
  create_user_skill: "创建自定义技能",
  mcp__whitz_files__list_workspace_files: "查看工作区文件",
  mcp__whitz_files__read_workspace_file: "读取工作区文件",
  mcp__whitz_files__search_workspace_files: "检索工作区文件",
  mcp__whitz_files__write_workspace_file: "写入工作区文件",
  mcp__whitz_skills__list_user_skills: "查看可用技能",
  mcp__whitz_skills__preview_github_skill: "预览 GitHub 技能",
  mcp__whitz_skills__install_github_skill: "安装 GitHub 技能",
  mcp__whitz_skills__create_user_skill: "创建自定义技能",
};

interface WebItem {
  title: string;
  url: string;
  snippet: string;
}

function stripWrapper(raw?: string): string {
  if (!raw) return "";
  let text = raw.trim();
  if (text.startsWith("<untrusted_tool_result")) {
    const close = text.indexOf(">");
    text = close >= 0 ? text.slice(close + 1) : text;
  }
  const suffix = "</untrusted_tool_result>";
  if (text.trim().endsWith(suffix)) text = text.trim().slice(0, -suffix.length);
  return text.trim();
}

function parsePayload(raw?: string): any {
  const text = stripWrapper(raw);
  if (!text) return null;
  const starts = [text.indexOf("{"), text.indexOf("[")].filter((i) => i >= 0);
  const start = starts.length ? Math.min(...starts) : -1;
  if (start < 0) return null;
  try {
    return JSON.parse(text.slice(start));
  } catch {
    return null;
  }
}

function parseArgs(raw?: string): any {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return parsePayload(raw);
  }
}

function isWeb(tool: ReasoningTool): boolean {
  return tool.name === "web_search" || tool.name === "web_extract";
}

function webItems(tool: ReasoningTool): WebItem[] {
  const payload = parsePayload(tool.result);
  const items: any[] = Array.isArray(payload?.results)
    ? payload.results
    : Array.isArray(payload?.data?.web)
      ? payload.data.web
      : Array.isArray(payload?.web)
        ? payload.web
        : Array.isArray(payload?.data?.results)
          ? payload.data.results
          : [];
  return items
    .slice(0, 8)
    .map((x: any): WebItem => ({
      title: String(x?.title ?? x?.name ?? ""),
      url: String(x?.url ?? x?.link ?? ""),
      snippet: String(x?.description ?? x?.snippet ?? x?.content ?? "").slice(0, 500),
    }))
    .filter((x) => x.title || x.url);
}

function webQuery(tool: ReasoningTool): string {
  if (tool.name !== "web_search") return "";
  const args = parseArgs(tool.args);
  return typeof args?.query === "string" ? args.query : "";
}

function todoChanges(tool: ReasoningTool): string[] {
  const args = parseArgs(tool.args);
  const todos = Array.isArray(args?.todos) ? args.todos : [];
  return todos
    .map((x: any) => {
      const content = String(x?.content ?? "").trim();
      const status = STATUS_LABELS[x?.status] ?? x?.status ?? "";
      return content && status ? `${content}（${status}）` : content;
    })
    .filter(Boolean);
}

const SEARCH_PROVIDER_LABELS: Record<string, string> = {
  bocha: "博查",
  tavily: "Tavily",
  duckduckgo: "DuckDuckGo",
};

function webSearchProviderLabel(tool: ReasoningTool): string {
  if (tool.name !== "web_search") return "";
  const payload = parsePayload(tool.result);
  const resProvider = typeof payload?.provider === "string" ? payload.provider.toLowerCase() : "";
  if (resProvider && SEARCH_PROVIDER_LABELS[resProvider]) return SEARCH_PROVIDER_LABELS[resProvider];
  const args = parseArgs(tool.args);
  const argProvider = typeof args?.provider === "string" ? args.provider.toLowerCase() : "";
  return SEARCH_PROVIDER_LABELS[argProvider] ?? "";
}

function toolLabel(tool: ReasoningTool): string {
  const base = TOOL_LABELS[tool.name] ?? tool.name;
  if (tool.name === "web_search") {
    const providerLabel = webSearchProviderLabel(tool);
    if (providerLabel) return `${base} · ${providerLabel}`;
  }
  return base;
}

function toolSummary(tool: ReasoningTool): string {
  if (tool.name === "web_search") return webQuery(tool);
  if (tool.name === "web_extract") return webItems(tool)[0]?.title ?? "";
  if (tool.name === "todo_list") return todoChanges(tool)[0] ?? "";
  if (tool.name === "tool_describe") {
    const args = parseArgs(tool.args);
    return Array.isArray(args?.names) ? args.names.join("、") : "";
  }
  if (tool.name === "skill_view") {
    const args = parseArgs(tool.args);
    return typeof args?.name === "string" ? args.name : "";
  }
  if (tool.name === "clarify") {
    const args = parseArgs(tool.args);
    return typeof args?.question === "string" ? args.question : "";
  }
  const args = stripWrapper(tool.args);
  return (args || stripWrapper(tool.result)).split("\n")[0]?.slice(0, 80) ?? "";
}

function collapsedTitles(tool: ReasoningTool): string[] {
  if (!isWeb(tool)) return [];
  return webItems(tool)
    .map((item) => item.title)
    .filter(Boolean)
    .slice(0, 3);
}

function pretty(raw?: string): string {
  const text = stripWrapper(raw);
  if (!text) return "";
  try {
    const parsed = JSON.parse(text);
    const formatted = JSON.stringify(parsed, null, 2);
    return formatted.length > 1800 ? formatted.slice(0, 1800) + "…" : formatted;
  } catch {
    return text.length > 1200 ? text.slice(0, 1200) + "…" : text;
  }
}

function prettyArgs(tool: ReasoningTool): string {
  return pretty(tool.args);
}

function prettyResult(tool: ReasoningTool): string {
  return pretty(tool.result);
}
</script>

<template>
  <div class="space-y-1.5">
    <div v-if="block.content" class="rounded-md bg-surface/60 px-2.5 py-2">
      <p class="mb-0.5 text-[11.5px] font-medium uppercase tracking-wide text-fg-faint">过程回复</p>
      <div :class="longContent ? ['clamp-expandable', { 'is-expanded': contentOpen }] : ''">
        <p class="whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg-muted">
          {{ block.content }}
        </p>
      </div>
      <button
        v-if="longContent"
        type="button"
        class="mt-0.5 text-[12.5px] text-accent transition-opacity hover:opacity-70"
        @click="contentOpen = !contentOpen"
      >
        {{ contentOpen ? "收起" : "展开全文" }}
      </button>
    </div>

    <div v-if="block.text">
      <div :class="longText ? ['clamp-expandable', { 'is-expanded': textOpen }] : ''">
        <p class="whitespace-pre-wrap break-words text-[13.5px] leading-relaxed text-fg-muted">
          {{ block.text }}
        </p>
      </div>
      <button
        v-if="longText"
        type="button"
        class="mt-0.5 text-[12.5px] text-accent transition-opacity hover:opacity-70"
        @click="textOpen = !textOpen"
      >
        {{ textOpen ? "收起" : "展开全文" }}
      </button>
    </div>

    <div v-if="block.tools?.length" class="space-y-1.5">
      <div
        v-for="(tool, ti) in block.tools"
        :key="ti"
        class="overflow-hidden rounded-lg bg-surface/65"
      >
        <details :open="openTools.has(ti)" class="disclosure-card">
          <summary
            class="focus-ring flex w-full cursor-pointer items-center gap-1.5 px-2.5 py-2 text-left"
            @click.prevent="toggleTool(ti)"
          >
            <svg class="h-3.5 w-3.5 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M14.7 6.3a4 4 0 00-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 005.4-5.4l-2.3 2.3-2.1-2.1 2.4-2.2z"
              />
            </svg>
            <span class="shrink-0 text-[12.5px] font-medium text-fg-muted">{{ toolLabel(tool) }}</span>
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-fg-faint">{{ toolSummary(tool) }}</span>
            <svg
              class="h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform duration-200"
              :class="openTools.has(ti) ? 'rotate-90' : ''"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
            </svg>
          </summary>

          <div class="space-y-1.5 px-2.5 pb-2.5 pt-1">
          <template v-if="isWeb(tool)">
            <p v-if="webQuery(tool)" class="text-[12.5px] text-fg-faint">搜索：{{ webQuery(tool) }}</p>
            <div v-for="(item, ii) in webItems(tool)" :key="ii" class="space-y-0.5">
              <p class="text-[12.5px] font-medium leading-snug text-fg-muted">{{ item.title || item.url }}</p>
              <a
                v-if="item.url"
                :href="item.url"
                target="_blank"
                rel="noopener noreferrer"
                class="block truncate text-[11.5px] text-accent hover:underline"
              >
                {{ item.url }}
              </a>
              <p
                v-if="item.snippet"
                class="line-clamp-4 whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-fg-faint"
              >
                {{ item.snippet }}
              </p>
            </div>
            <p v-if="!webItems(tool).length" class="text-[12.5px] text-fg-faint">暂无结果详情</p>
          </template>

          <template v-else-if="tool.name === 'todo_list'">
            <p
              v-for="(change, ci) in todoChanges(tool)"
              :key="ci"
              class="text-[12.5px] leading-relaxed text-fg-faint"
            >
              · {{ change }}
            </p>
          </template>

          <template v-else>
            <div v-if="prettyArgs(tool)">
              <p class="mb-0.5 text-[11.5px] font-medium uppercase tracking-wide text-fg-faint">参数</p>
              <pre class="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-surface/60 p-1.5 text-[11.5px] leading-relaxed text-fg-faint">{{ prettyArgs(tool) }}</pre>
            </div>
            <div v-if="prettyResult(tool)">
              <p class="mb-0.5 text-[11.5px] font-medium uppercase tracking-wide text-fg-faint">结果</p>
              <pre class="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-surface/60 p-1.5 text-[11.5px] leading-relaxed text-fg-faint">{{ prettyResult(tool) }}</pre>
            </div>
          </template>
          </div>
        </details>

        <div v-if="collapsedTitles(tool).length" class="collapse-panel" :class="{ 'is-open': !openTools.has(ti) }">
          <div class="space-y-0.5 px-2.5 pb-2">
            <p
              v-for="(title, ci) in collapsedTitles(tool)"
              :key="ci"
              class="truncate text-[12.5px] leading-relaxed text-fg-faint"
            >
              · {{ title }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
