<script setup lang="ts">
import { computed, ref } from "vue";
import hljs from "highlight.js";
import type { WorkspaceFileContent } from "@shared/work-types";

const props = defineProps<{
  file?: WorkspaceFileContent | null;
  diff?: { path: string; diff: string } | null;
}>();

const emit = defineEmits<{
  close: [];
  openExplorer: [string];
  insertPath: [string];
}>();

const copied = ref(false);

const highlightedHtml = computed(() => {
  if (!props.file || props.file.binary) return "";
  const code = props.file.content;
  const lang = props.file.language;
  try {
    if (lang && lang !== "plaintext" && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    }
    return hljs.highlightAuto(code).value;
  } catch {
    return code
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
});

const diffLines = computed(() => {
  if (!props.diff?.diff) return [];
  return props.diff.diff.split(/\r?\n/);
});

async function copyTargetPath() {
  const target = props.file?.rel_path ?? props.diff?.path;
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target);
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1500);
  } catch {
    /* ignore */
  }
}

function diffLineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) return "bg-[#193524]/70 text-[#9ce5b4]";
  if (line.startsWith("-") && !line.startsWith("---")) return "bg-[#3d1c1c]/70 text-[#f3a6a0]";
  if (line.startsWith("@@")) return "bg-[#1f293d]/70 text-[#93c5fd]";
  if (line.startsWith("diff ") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++")) {
    return "text-[#9ca3af]";
  }
  return "text-[#d6d5ce]";
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-canvas">
    <div class="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
      <div class="min-w-0 flex-1">
        <p class="truncate text-[12px] font-medium text-fg" :title="file?.rel_path ?? diff?.path">
          {{ file ? file.rel_path : diff?.path }}
        </p>
        <p v-if="file" class="text-[10.5px] text-fg-faint">
          {{ file.language }} · {{ (file.size / 1024).toFixed(1) }} KB
          <span v-if="file.truncated"> · 已截断前 512KB</span>
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-1">
        <button
          v-if="file"
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          title="引用到输入框 (@)"
          @click="emit('insertPath', file.rel_path)"
        >
          @引用
        </button>
        <button
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          @click="copyTargetPath"
        >
          {{ copied ? "已复制" : "复制路径" }}
        </button>
        <button
          v-if="file"
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          title="在资源管理器中定位"
          @click="emit('openExplorer', file.rel_path)"
        >
          定位
        </button>
        <button
          type="button"
          class="rounded-lg p-1 text-fg-faint hover:bg-hover hover:text-fg"
          aria-label="关闭预览"
          @click="emit('close')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </div>

    <div v-if="file?.binary" class="flex flex-1 items-center justify-center p-6 text-center text-[12px] text-fg-faint">
      二进制文件不支持文本预览，可使用右上角「定位」在系统默认应用中打开。
    </div>

    <div v-else-if="file" class="min-h-0 flex-1 overflow-auto custom-scrollbar bg-code p-3">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <pre class="hljs m-0 bg-transparent p-0 font-mono text-[11.5px] leading-relaxed text-[#e6e5e0]"><code v-html="highlightedHtml" /></pre>
    </div>

    <div v-else-if="diff" class="min-h-0 flex-1 overflow-auto custom-scrollbar bg-code p-2.5">
      <div v-if="!diffLines.length" class="p-4 text-center text-[12px] text-[#9ca3af]">暂无差异内容</div>
      <pre v-else class="m-0 font-mono text-[11px] leading-relaxed"><span
        v-for="(line, idx) in diffLines"
        :key="idx"
        class="block whitespace-pre-wrap break-all px-1.5"
        :class="diffLineClass(line)"
      >{{ line || " " }}</span></pre>
    </div>
  </div>
</template>
