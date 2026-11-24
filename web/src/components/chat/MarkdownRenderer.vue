<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import MarkdownIt, { type StateBlock, type StateInline, type Token } from "markdown-it";
import hljs from "highlight.js/lib/common";
import katex from "katex";

import type { CitationItem, DeliverableTarget } from "../../types";

const props = defineProps<{
  content: string;
  streaming?: boolean;
  citations?: CitationItem[];
}>();

const emit = defineEmits<{
  "preview-html": [html: string];
  "open-deliverable": [target: DeliverableTarget];
  "open-citation": [citationId: string];
}>();

const containerRef = ref<HTMLElement | null>(null);
const renderedNodeHtml = new WeakMap<Element, string>();
let pendingRenderTimer: number | null = null;
let pendingRenderRaf: number | null = null;

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
  '<svg class="md-icon-copy icon-m icon-m-copy" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M5.5 15H4.8A1.8 1.8 0 0 1 3 13.2V4.8A1.8 1.8 0 0 1 4.8 3h8.4A1.8 1.8 0 0 1 15 4.8v.7"></path>' +
  '<g class="icon-part icon-part-front"><rect class="icon-duotone-fill" x="9" y="9" width="11.5" height="11.5" rx="2.5"></rect><rect x="9" y="9" width="11.5" height="11.5" rx="2.5"></rect><path class="icon-grow" pathLength="1" d="M12.2 13.2h5.2"></path><path class="icon-grow icon-d1" pathLength="1" d="M12.2 16.2h3.4"></path></g>' +
  "</svg>";

const CHECK_ICON_SVG =
  '<svg class="md-icon-check icon-m icon-m-check-draw" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path class="icon-check-path" d="M5 12.8l4.4 4.4L19 7.5"></path>' +
  "</svg>";

const PREVIEW_ICON_SVG =
  '<svg class="icon-m icon-m-pop" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path class="icon-duotone-fill" d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z"></path>' +
  '<path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z"></path>' +
  '<circle cx="12" cy="12" r="2.8"></circle>' +
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

function parseCitationInline(state: StateInline, silent: boolean): boolean {
  const pos = state.pos;
  const src = state.src;
  if (src.charCodeAt(pos) !== 0x5b /* [ */ || src.charCodeAt(pos + 1) !== 0x5b /* [ */) {
    return false;
  }
  const rest = src.slice(pos, Math.min(state.posMax, pos + 64));
  const match = /^\[\[cite:([A-Za-z]\d+(?:\s*,\s*[A-Za-z]\d+)*)\]\]/i.exec(rest);
  if (!match) return false;
  if (!silent) {
    const token = state.push("rag_citation", "", 0);
    token.content = match[1];
  }
  state.pos = pos + match[0].length;
  return true;
}

md.block.ruler.after("blockquote", "math_block", parseMathBlock, {
  alt: ["paragraph", "reference", "blockquote", "list"],
});
md.inline.ruler.before("escape", "math_inline", parseMathInline);
md.inline.ruler.before("link", "rag_citation", parseCitationInline);

md.renderer.rules.rag_citation = (tokens: Token[], idx: number) => {
  const rawIds = tokens[idx].content
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
  return rawIds
    .map((cid) => {
      const num = cid.replace(/^[A-Z]+/i, "") || cid;
      const safeId = md.utils.escapeHtml(cid);
      const safeNum = md.utils.escapeHtml(num);
      return `<button type="button" class="md-cite-badge" data-action="open-citation" data-cite-id="${safeId}" aria-label="查看引用来源 ${safeId}" title="来源 ${safeId}">${safeNum}</button>`;
    })
    .join("");
};

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

  if (langLower === "deliverable" || langLower === "whitz-deliverable") {
    let parsed: { file_id?: string; id?: string; filename?: string; title?: string; summary?: string } | null = null;
    try {
      const obj = JSON.parse(rawCode.trim());
      if (obj && typeof obj === "object") parsed = obj;
    } catch {
      parsed = null;
    }
    const fid = String(parsed?.file_id || parsed?.id || "").trim();
    const fname = String(parsed?.filename || "").trim();
    const title = String(parsed?.title || fname || "交付产物").trim();
    const summary = String(parsed?.summary || "").trim();

    if (!fid || !fname) {
      return (
        '<div class="md-deliverable-card is-loading">' +
        '<span class="md-deliverable-badge">交付</span>' +
        '<div class="md-deliverable-info">' +
        '<div class="md-deliverable-title">正在生成交互交付卡片…</div>' +
        "</div>" +
        "</div>"
      );
    }

    const dotIdx = fname.lastIndexOf(".");
    const extLabel = dotIdx >= 0 ? fname.slice(dotIdx + 1).toUpperCase() : "TEXT";
    const actionLabel =
      extLabel === "HTML" || extLabel === "HTM"
        ? "查看页面"
        : extLabel === "CSV" || extLabel === "TSV"
          ? "查看表格"
          : "弹窗查看";

    return (
      `<button type="button" class="md-deliverable-card" data-action="open-deliverable"` +
      ` data-file-id="${md.utils.escapeHtml(fid)}"` +
      ` data-filename="${md.utils.escapeHtml(fname)}"` +
      ` data-title="${md.utils.escapeHtml(title)}"` +
      ` data-summary="${md.utils.escapeHtml(summary)}">` +
      `<span class="md-deliverable-badge">${md.utils.escapeHtml(extLabel)}</span>` +
      '<span class="md-deliverable-info">' +
      `<span class="md-deliverable-title">${md.utils.escapeHtml(title)}</span>` +
      (summary ? `<span class="md-deliverable-summary">${md.utils.escapeHtml(summary)}</span>` : "") +
      `<span class="md-deliverable-file">${md.utils.escapeHtml(fname)}</span>` +
      "</span>" +
      `<span class="md-deliverable-cta">${PREVIEW_ICON_SVG}<span>${actionLabel}</span></span>` +
      "</button>"
    );
  }

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

  if (block.dataset.streamingUnclosed === "true") {
    block.dataset.state = "loading";
    block.dataset.view = "diagram";
    errorEl.textContent = "";
    const loadingEl = diagramEl.querySelector<HTMLElement>(".md-mermaid-loading");
    if (loadingEl) loadingEl.textContent = "正在生成图表代码…";
    return;
  }

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
  if (block.dataset.state === "ready" && block.dataset.mermaidKey === cacheKey) {
    block.dataset.view = preferredView;
    toggleBtn?.setAttribute("aria-pressed", String(preferredView === "source"));
    return;
  }
  const cached = mermaidSvgCache.get(cacheKey);
  if (cached) {
    diagramEl.innerHTML = cached;
    errorEl.textContent = "";
    block.dataset.state = "ready";
    block.dataset.mermaidKey = cacheKey;
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
    block.dataset.mermaidKey = cacheKey;
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
  const action = btn.dataset.action;

  if (action === "open-citation") {
    const citeId = btn.dataset.citeId?.trim();
    if (citeId) emit("open-citation", citeId);
    return;
  }

  if (action === "open-deliverable") {
    const fileId = btn.dataset.fileId?.trim();
    const filename = btn.dataset.filename?.trim();
    if (fileId && filename) {
      emit("open-deliverable", {
        fileId,
        filename,
        title: btn.dataset.title?.trim() || filename,
        summary: btn.dataset.summary?.trim() || undefined,
      });
    }
    return;
  }

  const block = btn.closest<HTMLElement>(".md-code-block");
  if (!block) return;

  if (action === "copy") {
    void handleCopyBlock(block, btn);
  } else if (action === "preview-html") {
    emit("preview-html", extractBlockCode(block));
  } else if (action === "toggle-mermaid") {
    handleToggleMermaid(block, btn, target);
  }
}

function detectUnclosedTrailingFence(src: string): string | null {
  let openLang: string | null = null;
  for (const rawLine of src.split(/\r?\n/)) {
    const trimmed = rawLine.trim();
    if (trimmed.startsWith("```")) {
      if (openLang === null) {
        openLang = trimmed.slice(3).trim().split(/\s+/)[0]?.toLowerCase() ?? "";
      } else {
        openLang = null;
      }
    }
  }
  return openLang;
}

function patchDirectChildren(liveEl: HTMLElement, nextEl: HTMLElement) {
  const nextChildren = Array.from(nextEl.children);
  for (let i = 0; i < nextChildren.length; i++) {
    const nextChild = nextChildren[i];
    const nextHtml = nextChild.outerHTML;
    const liveChild = liveEl.children[i];
    if (liveChild && renderedNodeHtml.get(liveChild) === nextHtml) {
      continue;
    }
    const prevScrollLeft =
      liveChild?.classList.contains("md-code-block")
        ? (liveChild.querySelector<HTMLElement>(".md-code-pre")?.scrollLeft ?? 0)
        : 0;
    renderedNodeHtml.set(nextChild, nextHtml);
    if (liveChild) {
      liveEl.replaceChild(nextChild, liveChild);
    } else {
      liveEl.appendChild(nextChild);
    }
    if (prevScrollLeft > 0) {
      const nextPre = nextChild.querySelector<HTMLElement>(".md-code-pre");
      if (nextPre) nextPre.scrollLeft = prevScrollLeft;
    }
  }
  while (liveEl.children.length > nextChildren.length) {
    liveEl.lastElementChild?.remove();
  }
}

function cancelScheduledRender() {
  if (pendingRenderTimer !== null) {
    window.clearTimeout(pendingRenderTimer);
    pendingRenderTimer = null;
  }
  if (pendingRenderRaf !== null) {
    window.cancelAnimationFrame(pendingRenderRaf);
    pendingRenderRaf = null;
  }
}

async function renderContent() {
  const el = containerRef.value;
  if (!el) return;
  const seq = ++renderSeq;
  const raw = props.content ?? "";
  const rendered = md.render(raw);

  const DOMPurify = cachedDOMPurify ?? (await loadDOMPurify());
  if (seq !== renderSeq || !containerRef.value) return;

  const staging = document.createElement("div");
  staging.innerHTML = DOMPurify.sanitize(rendered, DOMPURIFY_CONFIG);

  for (const anchor of staging.querySelectorAll("a")) {
    anchor.setAttribute("target", "_blank");
    anchor.setAttribute("rel", "noopener noreferrer");
  }

  if (props.citations?.length) {
    const citeMap = new Map(props.citations.map((c) => [c.citation_id.toUpperCase(), c]));
    for (const badge of staging.querySelectorAll<HTMLButtonElement>("button.md-cite-badge[data-cite-id]")) {
      const cid = (badge.dataset.citeId || "").toUpperCase();
      const item = citeMap.get(cid);
      if (item) {
        const header = [item.title, item.subtitle].filter(Boolean).join(" · ");
        const snippet = item.snippet ? `\n${item.snippet.slice(0, 140)}` : "";
        badge.setAttribute("title", `${header}${snippet}`);
        badge.setAttribute("aria-label", `查看引用 ${cid}：${header}`);
      }
    }
  }

  if (props.streaming) {
    const unclosedLang = detectUnclosedTrailingFence(raw);
    if (unclosedLang !== null) {
      const codeBlocks = staging.querySelectorAll<HTMLElement>(".md-code-block");
      const lastCode = codeBlocks[codeBlocks.length - 1];
      if (lastCode) {
        if (unclosedLang === "mermaid" && lastCode.classList.contains("md-mermaid-block")) {
          lastCode.dataset.streamingUnclosed = "true";
        }
        const langEl = lastCode.querySelector<HTMLElement>(".md-code-lang");
        if (langEl && !langEl.querySelector(".md-code-streaming-badge")) {
          const badge = document.createElement("span");
          badge.className = "md-code-streaming-badge";
          badge.innerHTML = '<span class="md-code-streaming-dot" aria-hidden="true"></span><span>生成中…</span>';
          langEl.appendChild(badge);
        }
      }
    }
  }

  patchDirectChildren(el, staging);
  await renderMermaidBlocks(el, seq);
}

function scheduleRender(immediate = false) {
  if (immediate || !props.streaming) {
    cancelScheduledRender();
    void renderContent();
    return;
  }
  if (pendingRenderTimer !== null || pendingRenderRaf !== null) return;
  pendingRenderTimer = window.setTimeout(() => {
    pendingRenderTimer = null;
    pendingRenderRaf = window.requestAnimationFrame(() => {
      pendingRenderRaf = null;
      void renderContent();
    });
  }, 32);
}

watch(
  () => props.content,
  (next, prev) => {
    if (!prev || !next.startsWith(prev.slice(0, Math.min(24, prev.length)))) {
      mermaidViewOverrides.clear();
    }
    scheduleRender(!props.streaming);
  },
);

watch(
  () => props.streaming,
  (nowStreaming, wasStreaming) => {
    if (wasStreaming && !nowStreaming) {
      scheduleRender(true);
    }
  },
);

watch(
  () => props.citations?.length ?? 0,
  () => {
    if (props.content.includes("[[cite:")) {
      scheduleRender(true);
    }
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
  cancelScheduledRender();
  themeObserver?.disconnect();
  themeObserver = null;
  for (const timer of copyTimers.values()) {
    window.clearTimeout(timer);
  }
  copyTimers.clear();
});
</script>

<template>
  <div ref="containerRef" class="markdown-body" :class="{ 'is-streaming': streaming }" @click="onContainerClick" />
</template>
