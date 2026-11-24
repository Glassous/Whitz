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
  openEditor: [string];
  insertPath: [string];
}>();

const copied = ref(false);

const isImageFile = computed(() => Boolean(props.file && props.file.language === "image" && props.file.content.startsWith("data:")));

const highlightedLines = computed<string[]>(() => {
  if (!props.file || props.file.binary || isImageFile.value) return [];
  const code = props.file.content;
  const lang = props.file.language;
  let html = "";
  try {
    if (lang && lang !== "plaintext" && hljs.getLanguage(lang)) {
      html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    } else {
      html = hljs.highlightAuto(code).value;
    }
  } catch {
    html = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  return html.split(/\r?\n/);
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
        <p class="truncate font-mono text-[12px] font-medium text-fg" :title="file?.rel_path ?? diff?.path">
          {{ file ? file.rel_path : diff?.path }}
        </p>
        <p v-if="file" class="text-[10.5px] text-fg-faint">
          {{ file.language }} · {{ (file.size / 1024).toFixed(1) }} KB
          <span v-if="!isImageFile && !file.binary"> · {{ highlightedLines.length }} 行</span>
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
          {{ copied ? "已复制" : "复制" }}
        </button>
        <button
          v-if="file"
          type="button"
          class="rounded-lg px-1.5 py-1 text-[11px] text-fg-muted hover:bg-hover hover:text-fg"
          title="用系统默认编辑器打开"
          @click="emit('openEditor', file.rel_path)"
        >
          编辑
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

    <!-- Image Preview -->
    <div v-if="isImageFile && file" class="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-code p-4">
      <img :src="file.content" :alt="file.rel_path" class="max-h-full max-w-full rounded-lg object-contain shadow" />
    </div>

    <!-- Binary Notice -->
    <div v-else-if="file?.binary" class="flex flex-1 items-center justify-center p-6 text-center text-[12px] text-fg-faint">
      二进制文件不支持文本预览，可使用右上角「编辑」或「定位」在系统应用中打开。
    </div>

    <!-- Code Preview with Line Numbers -->
    <div v-else-if="file" class="min-h-0 flex-1 overflow-auto custom-scrollbar bg-code py-2.5 font-mono text-[11.5px] leading-[1.55]">
      <div v-for="(lineHtml, idx) in highlightedLines" :key="idx" class="flex items-stretch px-2 hover:bg-white/[0.03]">
        <span class="w-10 shrink-0 select-none pr-3 text-right text-[10.5px] text-white/30 tabular-nums">
          {{ idx + 1 }}
        </span>
        <!-- eslint-disable-next-line vue/no-v-html -->
        <span class="hljs min-w-0 flex-1 whitespace-pre text-[#e6e5e0]" v-html="lineHtml || ' '" />
      </div>
    </div>

    <!-- Legacy Fallback Diff -->
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
