<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import MarkdownIt from "markdown-it";
import hljs from "highlight.js/lib/common";

const props = defineProps<{ content: string }>();

const containerRef = ref<HTMLElement | null>(null);
let domPurifyPromise: Promise<typeof import("dompurify").default> | undefined;
let renderSeq = 0;

function loadDOMPurify() {
  domPurifyPromise ??= import("dompurify").then((mod) => mod.default ?? mod);
  return domPurifyPromise;
}

const md: MarkdownIt = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(str, lang): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang, ignoreIllegals: true }).value;
      } catch {
        /* fall through */
      }
    }
    return md.utils.escapeHtml(str);
  },
});

async function renderContent() {
  const el = containerRef.value;
  if (!el) return;
  const seq = ++renderSeq;
  const rendered = md.render(props.content ?? "");

  if ("setHTML" in Element.prototype) {
    (el as HTMLElement & { setHTML: (html: string) => void }).setHTML(rendered);
  } else {
    const DOMPurify = await loadDOMPurify();
    if (seq !== renderSeq) return;
    el.innerHTML = DOMPurify.sanitize(rendered, { USE_PROFILES: { html: true } });
  }

  for (const anchor of el.querySelectorAll("a")) {
    anchor.setAttribute("target", "_blank");
    anchor.setAttribute("rel", "noopener noreferrer");
  }
}

watch(() => props.content, () => {
  void renderContent();
});

onMounted(() => {
  void renderContent();
});
</script>

<template>
  <div ref="containerRef" class="markdown-body" />
</template>
