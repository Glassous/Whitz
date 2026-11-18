<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import MarkdownIt, { type StateBlock, type StateInline, type Token } from "markdown-it";
import hljs from "highlight.js/lib/common";
import katex from "katex";

const props = defineProps<{ content: string }>();

const emit = defineEmits<{
  "preview-html": [html: string];
}>();

const containerRef = ref<HTMLElement | null>(null);

let domPurifyPromise: Promise<typeof import("dompurify").default> | undefined;
let cachedDOMPurify: typeof import("dompurify").default | null = null;
let mermaidPromise: Promise<typeof import("mermaid").default> | undefined;
let renderSeq = 0;
let mermaidIdSeq = 0;
let lastInitializedTheme: "dark" | "neutral" | null = null;
let mermaidRenderQueue: Promise<void> = Promise.resolve();
let lastObservedDark =
  typeof document !== "undefined" ? document.documentElement.classList.contains("dark") : false;
let themeObserver: MutationObserver | null = null;

const MAX_MERMAID_CACHE = 80;
const mermaidSvgCache = new Map<string, string>();
const mermaidViewOverrides = new Map<number, "diagram" | "source">();
const copyTimers = new Map<HTMLButtonElement, number>();

function loadDOMPurify() {
  domPurifyPromise ??= import("dompurify").then((mod) => {
    const resolved = mod.default ?? mod;
    cachedDOMPurify = resolved;
    return resolved;
  });
  return domPurifyPromise;
}

function loadMermaid() {
  mermaidPromise ??= import("mermaid").then((mod) => mod.default ?? mod);
  return mermaidPromise;
}

function cacheMermaidSvg(key: string, svg: string) {
  if (mermaidSvgCache.size >= MAX_MERMAID_CACHE) {
    const oldest = mermaidSvgCache.keys().next().value;
    if (oldest !== undefined) mermaidSvgCache.delete(oldest);
  }
  mermaidSvgCache.set(key, svg);
}

function isEscapedAt(src: string, idx: number): boolean {
  let backslashes = 0;
  let pos = idx - 1;
  while (pos >= 0 && src.charCodeAt(pos) === 0x5c /* \ */) {
    backslashes++;
    pos--;
  }
  return backslashes % 2 === 1;
}

function isWhitespace(ch: number): boolean {
  return ch === 0x20 || ch === 0x09 || ch === 0x0a || ch === 0x0d;
}

function isAsciiDigit(ch: number): boolean {
  return ch >= 0x30 && ch <= 0x39;
}

function findClosingDelim(line: string, delim: "$$" | "\\]"): number {
  for (let i = 0; i <= line.length - 2; i++) {
    if (line.slice(i, i + 2) === delim && !isEscapedAt(line, i)) {
      return i;
    }
  }
  return -1;
}

function parseMathBlock(state: StateBlock, startLine: number, endLine: number, silent: boolean): boolean {
  const pos = state.bMarks[startLine] + state.tShift[startLine];
  const max = state.eMarks[startLine];

  if (state.sCount[startLine] - state.blkIndent >= 4) return false;
  if (pos + 2 > max) return false;

  const openDelim = state.src.slice(pos, pos + 2);
  let closeDelim: "$$" | "\\]" | null = null;
  if (openDelim === "$$") closeDelim = "$$";
  else if (openDelim === "\\[") closeDelim = "\\]";
  else return false;

  const firstLineAfter = state.src.slice(pos + 2, max);
  const sameLineCloseIdx = findClosingDelim(firstLineAfter, closeDelim);
  if (sameLineCloseIdx >= 0) {
    const trailing = firstLineAfter.slice(sameLineCloseIdx + 2).trim();
    if (trailing.length > 0) return false;
    const content = firstLineAfter.slice(0, sameLineCloseIdx).trim();
    if (!content) return false;
    if (silent) return true;

    const token = state.push("math_block", "div", 0);
    token.block = true;
    token.content = content;
    token.markup = openDelim;
    token.map = [startLine, startLine + 1];
    state.line = startLine + 1;
    return true;
  }

  let nextLine = startLine + 1;
  let lastLineContent = "";
  let found = false;

  while (nextLine < endLine) {
    const lineStart = state.bMarks[nextLine] + state.tShift[nextLine];
    const lineMax = state.eMarks[nextLine];

    if (lineStart < lineMax && state.sCount[nextLine] < state.blkIndent) {
      break;
    }

    const lineText = state.src.slice(lineStart, lineMax);
    const closeIdx = findClosingDelim(lineText, closeDelim);
    if (closeIdx >= 0 && lineText.slice(closeIdx + 2).trim().length === 0) {
      lastLineContent = lineText.slice(0, closeIdx);
      found = true;
      break;
    }
    nextLine++;
  }

  if (!found) return false;
  if (silent) return true;

  const middleLines = state.getLines(startLine + 1, nextLine, state.blkIndent, false);
  const rawContent = [firstLineAfter, middleLines, lastLineContent].filter((part) => part.length > 0).join("\n");
  const content = rawContent.trim();

  const token = state.push("math_block", "div", 0);
  token.block = true;
  token.content = content;
  token.markup = openDelim;
  token.map = [startLine, nextLine + 1];
  state.line = nextLine + 1;
  return true;
}

function parseMathInline(state: StateInline, silent: boolean): boolean {
  const pos = state.pos;
  const max = state.posMax;
  const ch = state.src.charCodeAt(pos);

  if (isEscapedAt(state.src, pos)) return false;

  // \(...\) or \[...\]
  if (ch === 0x5c /* \ */) {
    if (pos + 1 >= max) return false;
    const next = state.src.charCodeAt(pos + 1);
    if (next !== 0x28 /* ( */ && next !== 0x5b /* [ */) return false;

    const isDisplay = next === 0x5b;
    const closeChar = isDisplay ? 0x5d /* ] */ : 0x29 /* ) */;

    for (let scan = pos + 2; scan < max - 1; scan++) {
      if (
        state.src.charCodeAt(scan) === 0x5c /* \ */ &&
        state.src.charCodeAt(scan + 1) === closeChar &&
        !isEscapedAt(state.src, scan)
      ) {
        const content = state.src.slice(pos + 2, scan).trim();
        if (!content) return false;
        if (!silent) {
          const token = state.push(isDisplay ? "math_display_inline" : "math_inline", "math", 0);
          token.markup = isDisplay ? "\\[" : "\\(";
          token.content = content;
        }
        state.pos = scan + 2;
        return true;
      }
    }
    return false;
  }

  if (ch !== 0x24 /* $ */) return false;

  // $$...$$ inline display math
  if (pos + 1 < max && state.src.charCodeAt(pos + 1) === 0x24) {
    for (let scan = pos + 2; scan < max - 1; scan++) {
      if (
        state.src.charCodeAt(scan) === 0x24 &&
        state.src.charCodeAt(scan + 1) === 0x24 &&
        !isEscapedAt(state.src, scan)
      ) {
        const content = state.src.slice(pos + 2, scan).trim();
        if (!content) return false;
        if (!silent) {
          const token = state.push("math_display_inline", "math", 0);
          token.markup = "$$";
          token.content = content;
        }
        state.pos = scan + 2;
        return true;
      }
    }
    return false;
  }

  // $...$ inline math with price false-positive guards
  if (pos + 2 >= max) return false;
  if (pos > 0 && isAsciiDigit(state.src.charCodeAt(pos - 1))) return false;
  if (isWhitespace(state.src.charCodeAt(pos + 1))) return false;

  for (let scan = pos + 1; scan < max; scan++) {
    const cur = state.src.charCodeAt(scan);
    if (cur === 0x5c /* \ */) {
      scan++;
      continue;
    }
    if (cur === 0x24 /* $ */) {
      if (scan + 1 < max && state.src.charCodeAt(scan + 1) === 0x24) {
        return false;
      }
      if (isWhitespace(state.src.charCodeAt(scan - 1))) return false;
      if (scan + 1 < max && isAsciiDigit(state.src.charCodeAt(scan + 1))) return false;

      const content = state.src.slice(pos + 1, scan);
      if (!content.trim()) return false;
      if (!silent) {
        const token = state.push("math_inline", "math", 0);
        token.markup = "$";
        token.content = content;
      }
      state.pos = scan + 1;
      return true;
    }
  }

  return false;
}

function renderKatexHtml(latex: string, displayMode: boolean, blockWrapper: boolean): string {
  let html: string;
  try {
    html = katex.renderToString(latex, {
      displayMode,
      throwOnError: false,
      strict: "ignore",
      trust: false,
    });
  } catch {
    html = `<code>${md.utils.escapeHtml(latex)}</code>`;
  }
  if (!displayMode) return html;
  return blockWrapper ? `<div class="md-math-block">${html}</div>` : `<span class="md-math-block">${html}</span>`;
}

const COPY_ICON_SVG =
  '<svg class="md-icon-copy" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true">' +
  '<rect x="9" y="9" width="11" height="11" rx="2.2"></rect>' +
  '<path stroke-linecap="round" stroke-linejoin="round" d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"></path>' +
  "</svg>";

const CHECK_ICON_SVG =
  '<svg class="md-icon-check" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">' +
  '<path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"></path>' +
  "</svg>";

const PREVIEW_ICON_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true">' +
  '<path stroke-linecap="round" stroke-linejoin="round" d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"></path>' +
  '<circle cx="12" cy="12" r="3"></circle>' +
  "</svg>";

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

md.block.ruler.after("blockquote", "math_block", parseMathBlock, {
  alt: ["paragraph", "reference", "blockquote", "list"],
});
md.inline.ruler.before("escape", "math_inline", parseMathInline);

md.renderer.rules.math_block = (tokens: Token[], idx: number) =>
  renderKatexHtml(tokens[idx].content, true, true);

md.renderer.rules.math_display_inline = (tokens: Token[], idx: number) =>
  renderKatexHtml(tokens[idx].content, true, false);

md.renderer.rules.math_inline = (tokens: Token[], idx: number) =>
  renderKatexHtml(tokens[idx].content, false, false);

md.renderer.rules.fence = (tokens: Token[], idx: number) => {
  const token = tokens[idx];
  const rawCode = token.content;
  const info = token.info.trim();
  const rawLang = info.split(/\s+/)[0] ?? "";
  const langLower = rawLang.toLowerCase();
  const safeLangClass = langLower.replace(/[^a-z0-9_+-]/g, "");
  const displayLang = md.utils.escapeHtml(rawLang || "text");
  const highlighted = md.options.highlight ? md.options.highlight(rawCode, langLower, "") : md.utils.escapeHtml(rawCode);
  const codeClassAttr = safeLangClass ? ` class="hljs language-${safeLangClass}"` : ' class="hljs"';

  const copyBtn =
    '<button type="button" class="md-code-btn md-copy-btn" data-action="copy" aria-label="复制代码" title="复制代码">' +
    COPY_ICON_SVG +
    CHECK_ICON_SVG +
    '<span class="md-copy-label">复制</span>' +
    "</button>";

  if (langLower === "mermaid") {
    return (
      '<div class="md-code-block md-mermaid-block" data-lang="mermaid" data-view="diagram">' +
      '<div class="md-code-header">' +
      '<span class="md-code-lang">mermaid</span>' +
      '<div class="md-code-actions">' +
      '<button type="button" class="md-code-btn md-mermaid-toggle" data-action="toggle-mermaid" aria-pressed="false" aria-label="切换图形与源码视图" title="切换图形 / 源码">' +
      '<span class="md-toggle-opt" data-opt="diagram">图形</span>' +
      '<span class="md-toggle-sep">/</span>' +
      '<span class="md-toggle-opt" data-opt="source">源码</span>' +
      "</button>" +
      copyBtn +
      "</div>" +
      "</div>" +
      '<div class="md-mermaid-diagram">' +
      '<div class="md-mermaid-loading">正在渲染图表…</div>' +
      "</div>" +
      '<div class="md-mermaid-error"></div>' +
      `<pre class="md-code-pre md-mermaid-source"><code${codeClassAttr}>${highlighted}</code></pre>` +
      "</div>"
    );
  }

  const previewHtmlBtn =
    langLower === "html" || langLower === "htm"
      ? '<button type="button" class="md-code-btn md-preview-html-btn" data-action="preview-html" aria-label="预览 HTML" title="预览 HTML">' +
        PREVIEW_ICON_SVG +
        "<span>预览 HTML</span>" +
        "</button>"
      : "";

  return (
    `<div class="md-code-block" data-lang="${md.utils.escapeHtml(langLower || "text")}">` +
    '<div class="md-code-header">' +
    `<span class="md-code-lang">${displayLang}</span>` +
    `<div class="md-code-actions">${previewHtmlBtn}${copyBtn}</div>` +
    "</div>" +
    `<pre class="md-code-pre"><code${codeClassAttr}>${highlighted}</code></pre>` +
    "</div>"
  );
};

const DOMPURIFY_CONFIG = {
  USE_PROFILES: { html: true, mathMl: true, svg: true },
  FORBID_TAGS: [
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "foreignobject",
    "use",
    "base",
    "meta",
    "link",
    "noscript",
    "template",
    "textarea",
    "select",
    "option",
  ],
};

function extractBlockCode(block: Element): string {
  const code = block.querySelector("pre > code")?.textContent ?? "";
  return code.endsWith("\n") ? code.slice(0, -1) : code;
}

async function copyText(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

async function handleCopyBlock(block: HTMLElement, btn: HTMLButtonElement) {
  const text = extractBlockCode(block);
  const ok = await copyText(text);
  if (!ok) return;

  btn.classList.add("is-copied");
  const label = btn.querySelector<HTMLElement>(".md-copy-label");
  if (label) label.textContent = "已复制";

  const prevTimer = copyTimers.get(btn);
  if (prevTimer !== undefined) window.clearTimeout(prevTimer);

  const timer = window.setTimeout(() => {
    btn.classList.remove("is-copied");
    if (label) label.textContent = "复制";
    copyTimers.delete(btn);
  }, 2000);
  copyTimers.set(btn, timer);
}

function formatMermaidError(err: unknown): string {
  const raw = err instanceof Error ? err.message : typeof err === "string" ? err : "";
  const firstLine = raw.split("\n")[0]?.trim() ?? "";
  if (firstLine && firstLine.length <= 120) {
    return `图表语法暂无法渲染，已回退为源码显示（${firstLine}）`;
  }
  return "图表语法暂无法渲染，已回退为源码显示";
}

function enqueueMermaidTask<T>(task: () => Promise<T>): Promise<T> {
  const run = mermaidRenderQueue.then(task, task);
  mermaidRenderQueue = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

async function renderSingleMermaidBlock(block: HTMLElement, seq: number, themeKey: "dark" | "neutral") {
  const diagramEl = block.querySelector<HTMLElement>(".md-mermaid-diagram");
  const errorEl = block.querySelector<HTMLElement>(".md-mermaid-error");
  if (!diagramEl || !errorEl) return;

  const idxNum = Number(block.dataset.mermaidIndex ?? "0");
  const preferredView = mermaidViewOverrides.get(idxNum) ?? "diagram";
  const toggleBtn = block.querySelector<HTMLButtonElement>(".md-mermaid-toggle");
  const source = extractBlockCode(block);
  if (!source.trim()) {
    block.dataset.state = "error";
    block.dataset.view = "source";
    toggleBtn?.setAttribute("aria-pressed", "true");
    errorEl.textContent = "图表内容为空，已显示源码";
    return;
  }

  const cacheKey = `${themeKey}:${source}`;
  const cached = mermaidSvgCache.get(cacheKey);
  if (cached) {
    diagramEl.innerHTML = cached;
    errorEl.textContent = "";
    block.dataset.state = "ready";
    block.dataset.view = preferredView;
    toggleBtn?.setAttribute("aria-pressed", String(preferredView === "source"));
    return;
  }

  try {
    const { svg, bindFunctions } = await enqueueMermaidTask(async () => {
      const mermaid = await loadMermaid();
      if (lastInitializedTheme !== themeKey) {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          suppressErrorRendering: true,
          theme: themeKey,
        });
        lastInitializedTheme = themeKey;
      }
      const id = `whitz-mermaid-${++mermaidIdSeq}`;
      return mermaid.render(id, source);
    });

    if (seq !== renderSeq || !block.isConnected) return;

    cacheMermaidSvg(cacheKey, svg);
    diagramEl.innerHTML = svg;
    bindFunctions?.(diagramEl);
    errorEl.textContent = "";
    block.dataset.state = "ready";
    const resolvedView = mermaidViewOverrides.get(idxNum) ?? "diagram";
    block.dataset.view = resolvedView;
    toggleBtn?.setAttribute("aria-pressed", String(resolvedView === "source"));
  } catch (err) {
    if (seq !== renderSeq || !block.isConnected) return;
    diagramEl.innerHTML = "";
    errorEl.textContent = formatMermaidError(err);
    block.dataset.state = "error";
    block.dataset.view = "source";
    toggleBtn?.setAttribute("aria-pressed", "true");
  }
}

async function renderMermaidBlocks(el: HTMLElement, seq: number) {
  const blocks = Array.from(el.querySelectorAll<HTMLElement>(".md-mermaid-block"));
  if (!blocks.length) return;

  const themeKey: "dark" | "neutral" = document.documentElement.classList.contains("dark")
    ? "dark"
    : "neutral";

  blocks.forEach((block, index) => {
    block.dataset.mermaidIndex = String(index);
    const savedView = mermaidViewOverrides.get(index);
    if (savedView) {
      block.dataset.view = savedView;
      block.querySelector<HTMLButtonElement>(".md-mermaid-toggle")?.setAttribute("aria-pressed", String(savedView === "source"));
    }
  });

  await Promise.all(blocks.map((block) => renderSingleMermaidBlock(block, seq, themeKey)));
}

function handleToggleMermaid(block: HTMLElement, btn: HTMLButtonElement, clickTarget: HTMLElement) {
  const idxNum = Number(block.dataset.mermaidIndex ?? "0");
  const currentView = block.dataset.view === "source" ? "source" : "diagram";

  if (block.dataset.state === "error") {
    const clickedOpt = clickTarget.closest<HTMLElement>("[data-opt]")?.dataset.opt;
    if (clickedOpt === "diagram") {
      const themeKey: "dark" | "neutral" = document.documentElement.classList.contains("dark")
        ? "dark"
        : "neutral";
      mermaidViewOverrides.set(idxNum, "diagram");
      void renderSingleMermaidBlock(block, renderSeq, themeKey);
    }
    return;
  }

  const nextView: "diagram" | "source" = currentView === "diagram" ? "source" : "diagram";
  block.dataset.view = nextView;
  btn.setAttribute("aria-pressed", String(nextView === "source"));
  mermaidViewOverrides.set(idxNum, nextView);
}

function onContainerClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (!target) return;
  const btn = target.closest<HTMLButtonElement>("button[data-action]");
  if (!btn) return;
  const block = btn.closest<HTMLElement>(".md-code-block");
  if (!block) return;

  const action = btn.dataset.action;
  if (action === "copy") {
    void handleCopyBlock(block, btn);
  } else if (action === "preview-html") {
    emit("preview-html", extractBlockCode(block));
  } else if (action === "toggle-mermaid") {
    handleToggleMermaid(block, btn, target);
  }
}

async function renderContent() {
  const el = containerRef.value;
  if (!el) return;
  const seq = ++renderSeq;
  const rendered = md.render(props.content ?? "");

  const DOMPurify = cachedDOMPurify ?? (await loadDOMPurify());
  if (seq !== renderSeq || !containerRef.value) return;

  el.innerHTML = DOMPurify.sanitize(rendered, DOMPURIFY_CONFIG);

  for (const anchor of el.querySelectorAll("a")) {
    anchor.setAttribute("target", "_blank");
    anchor.setAttribute("rel", "noopener noreferrer");
  }

  await renderMermaidBlocks(el, seq);
}

watch(
  () => props.content,
  (next, prev) => {
    if (!prev || !next.startsWith(prev.slice(0, Math.min(24, prev.length)))) {
      mermaidViewOverrides.clear();
    }
    void renderContent();
  },
);

onMounted(() => {
  lastObservedDark = document.documentElement.classList.contains("dark");
  themeObserver = new MutationObserver(() => {
    const nextDark = document.documentElement.classList.contains("dark");
    if (nextDark !== lastObservedDark) {
      lastObservedDark = nextDark;
      if (containerRef.value?.querySelector(".md-mermaid-block")) {
        void renderMermaidBlocks(containerRef.value, renderSeq);
      }
    }
  });
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  void renderContent();
});

onBeforeUnmount(() => {
  themeObserver?.disconnect();
  themeObserver = null;
  for (const timer of copyTimers.values()) {
    window.clearTimeout(timer);
  }
  copyTimers.clear();
});
</script>

<template>
  <div ref="containerRef" class="markdown-body" @click="onContainerClick" />
</template>
