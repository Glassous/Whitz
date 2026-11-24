<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import type { WorkPtyInfo, WorkShellOption } from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore } from "../../stores/work";

const HEIGHT_KEY = "whitz_work_terminal_height";
const DEFAULT_HEIGHT = 240;
const MIN_HEIGHT = 140;
const MAX_HEIGHT = 520;

const emit = defineEmits<{
  close: [];
}>();

const runtime = useRuntimeStore();
const work = useWorkStore();

const height = ref<number>(loadHeight());
const isResizing = ref(false);
let resizeStartY = 0;
let resizeStartHeight = DEFAULT_HEIGHT;

const ptys = ref<WorkPtyInfo[]>([]);
const shells = ref<WorkShellOption[]>([]);
const activePtyId = ref<string | null>(null);
const creating = ref(false);
const shellMenuOpen = ref(false);
const errorMsg = ref<string | null>(null);

const hostContainerRef = ref<HTMLElement | null>(null);

interface TerminalInstance {
  term: Terminal;
  fit: FitAddon;
  ws: WebSocket | null;
  el: HTMLDivElement;
  resizeObserver: ResizeObserver | null;
}

const instances = new Map<string, TerminalInstance>();
let themeObserver: MutationObserver | null = null;
let unsubGlobal: (() => void) | null = null;

function loadHeight(): number {
  if (typeof window === "undefined") return DEFAULT_HEIGHT;
  const raw = Number(window.localStorage.getItem(HEIGHT_KEY));
  return Number.isFinite(raw) ? Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, raw)) : DEFAULT_HEIGHT;
}

function isDarkMode(): boolean {
  return typeof document !== "undefined" && document.documentElement.classList.contains("dark");
}

function terminalTheme() {
  if (isDarkMode()) {
    return {
      background: "#0a0a0c",
      foreground: "#e6e5e0",
      cursor: "#e0a858",
      cursorAccent: "#0a0a0c",
      selectionBackground: "rgba(224, 168, 88, 0.28)",
      black: "#18181b",
      red: "#f87171",
      green: "#4ade80",
      yellow: "#fbbf24",
      blue: "#60a5fa",
      magenta: "#c084fc",
      cyan: "#22d3ee",
      white: "#e4e4e7",
      brightBlack: "#52525b",
      brightRed: "#fca5a5",
      brightGreen: "#86efac",
      brightYellow: "#fde047",
      brightBlue: "#93c5fd",
      brightMagenta: "#d8b4fe",
      brightCyan: "#67e8f9",
      brightWhite: "#ffffff",
    };
  }
  return {
    background: "#f8f9fa",
    foreground: "#18181b",
    cursor: "#b8722f",
    cursorAccent: "#ffffff",
    selectionBackground: "rgba(184, 114, 47, 0.22)",
    black: "#18181b",
    red: "#dc2626",
    green: "#15803d",
    yellow: "#b45309",
    blue: "#2563eb",
    magenta: "#7c3aed",
    cyan: "#0891b2",
    white: "#f4f4f5",
    brightBlack: "#71717a",
    brightRed: "#ef4444",
    brightGreen: "#16a34a",
    brightYellow: "#d97706",
    brightBlue: "#3b82f6",
    brightMagenta: "#8b5cf6",
    brightCyan: "#06b6d4",
    brightWhite: "#ffffff",
  };
}

function syncAllThemes() {
  const theme = terminalTheme();
  for (const inst of instances.values()) {
    inst.term.options.theme = theme;
  }
}

const activeDirectory = computed(() => work.current?.conversation.workspace_path || work.activeWorkspace?.path || null);

async function mountPtyInstance(pty: WorkPtyInfo) {
  if (instances.has(pty.id)) return;
  const host = hostContainerRef.value;
  if (!host) return;

  const el = document.createElement("div");
  el.className = "h-full w-full";
  el.style.display = activePtyId.value === pty.id ? "block" : "none";
  host.appendChild(el);

  const term = new Terminal({
    cursorBlink: true,
    fontFamily: '"JetBrains Mono", "Cascadia Code", Consolas, monospace',
    fontSize: 12.5,
    lineHeight: 1.35,
    scrollback: 5000,
    theme: terminalTheme(),
  });
  const fit = new FitAddon();
  const webLinks = new WebLinksAddon((_event, uri) => {
    void window.whitzDesktop?.openExternal(uri);
  });
  term.loadAddon(fit);
  term.loadAddon(webLinks);
  term.open(el);

  const inst: TerminalInstance = { term, fit, ws: null, el, resizeObserver: null };
  instances.set(pty.id, inst);

  try {
    const info = await window.whitzDesktop?.pty.connectInfo(pty.id, activeDirectory.value);
    if (!info) return;
    const ws = new WebSocket(info.ws_url);
    ws.binaryType = "arraybuffer";
    inst.ws = ws;

    ws.onopen = () => {
      try {
        fit.fit();
        void window.whitzDesktop?.pty
          .update(pty.id, { size: { rows: term.rows, cols: term.cols } }, activeDirectory.value)
          .catch(() => undefined);
      } catch {
        /* ignore */
      }
      if (activePtyId.value === pty.id) term.focus();
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        term.write(ev.data);
      } else if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data));
      }
    };

    ws.onclose = () => {
      term.write("\r\n\x1b[90m[终端连接已关闭]\x1b[0m\r\n");
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data);
      }
    });

    term.onResize(({ rows, cols }) => {
      void window.whitzDesktop?.pty
        .update(pty.id, { size: { rows, cols } }, activeDirectory.value)
        .catch(() => undefined);
    });

    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(() => {
        if (activePtyId.value === pty.id) {
          try {
            fit.fit();
          } catch {
            /* ignore */
          }
        }
      });
      ro.observe(host);
      inst.resizeObserver = ro;
    }
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : "连接终端失败";
  }
}

function disposePtyInstance(ptyId: string) {
  const inst = instances.get(ptyId);
  if (!inst) return;
  inst.resizeObserver?.disconnect();
  try {
    inst.ws?.close();
  } catch {
    /* ignore */
  }
  inst.term.dispose();
  inst.el.remove();
  instances.delete(ptyId);
}

function updateVisibleElement() {
  for (const [id, inst] of instances.entries()) {
    const visible = id === activePtyId.value;
    inst.el.style.display = visible ? "block" : "none";
    if (visible) {
      void nextTick(() => {
        try {
          inst.fit.fit();
          inst.term.focus();
        } catch {
          /* ignore */
        }
      });
    }
  }
}

async function createTerminal(shell?: WorkShellOption) {
  if (!runtime.ready || creating.value) return;
  shellMenuOpen.value = false;
  creating.value = true;
  errorMsg.value = null;
  try {
    const pty = await window.whitzDesktop?.pty.create({
      command: shell?.path,
      args: shell?.args,
      cwd: activeDirectory.value ?? undefined,
      title: shell?.name || `终端 ${ptys.value.length + 1}`,
      workspacePath: activeDirectory.value,
    });
    if (pty) {
      if (!ptys.value.some((p) => p.id === pty.id)) {
        ptys.value = [...ptys.value, pty];
      }
      activePtyId.value = pty.id;
      await nextTick();
      await mountPtyInstance(pty);
      updateVisibleElement();
    }
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : "创建终端失败";
  } finally {
    creating.value = false;
  }
}

async function closeTerminal(ptyId: string) {
  disposePtyInstance(ptyId);
  ptys.value = ptys.value.filter((p) => p.id !== ptyId);
  if (activePtyId.value === ptyId) {
    activePtyId.value = ptys.value[ptys.value.length - 1]?.id ?? null;
    updateVisibleElement();
  }
  await window.whitzDesktop?.pty.remove(ptyId, activeDirectory.value).catch(() => undefined);
}

function clearActiveTerminal() {
  if (!activePtyId.value) return;
  instances.get(activePtyId.value)?.term.clear();
}

async function syncExistingPtys() {
  if (!runtime.ready) return;
  try {
    const [shellList, existing] = await Promise.all([
      window.whitzDesktop?.pty.shells(activeDirectory.value).catch(() => []) ?? [],
      window.whitzDesktop?.pty.list(activeDirectory.value).catch(() => []) ?? [],
    ]);
    shells.value = shellList;
    ptys.value = existing;
    if (existing.length) {
      if (!activePtyId.value || !existing.some((p) => p.id === activePtyId.value)) {
        activePtyId.value = existing[0].id;
      }
      await nextTick();
      for (const p of existing) {
        await mountPtyInstance(p);
      }
      updateVisibleElement();
    } else {
      await createTerminal();
    }
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : "加载终端列表失败";
  }
}

function onResizePointerDown(e: PointerEvent) {
  const target = e.currentTarget as HTMLElement;
  target.setPointerCapture(e.pointerId);
  isResizing.value = true;
  resizeStartY = e.clientY;
  resizeStartHeight = height.value;
}

function onResizePointerMove(e: PointerEvent) {
  if (!isResizing.value) return;
  const maxByViewport = Math.max(MIN_HEIGHT, Math.floor(window.innerHeight * 0.65));
  height.value = Math.round(
    Math.min(Math.min(MAX_HEIGHT, maxByViewport), Math.max(MIN_HEIGHT, resizeStartHeight + (resizeStartY - e.clientY))),
  );
}

function onResizePointerUp(e: PointerEvent) {
  if (!isResizing.value) return;
  isResizing.value = false;
  const target = e.currentTarget as HTMLElement;
  if (target.hasPointerCapture(e.pointerId)) target.releasePointerCapture(e.pointerId);
  try {
    window.localStorage.setItem(HEIGHT_KEY, String(height.value));
  } catch {
    /* ignore */
  }
  updateVisibleElement();
}

watch(activePtyId, () => updateVisibleElement());

onMounted(() => {
  void syncExistingPtys();
  if (typeof MutationObserver !== "undefined") {
    themeObserver = new MutationObserver(() => syncAllThemes());
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  }
  unsubGlobal =
    window.whitzDesktop?.onWorkGlobalEvent((ev) => {
      if (ev.type === "pty.exited") {
        const id = String(ev.properties.id ?? "");
        const target = ptys.value.find((p) => p.id === id);
        if (target) target.status = "exited";
      } else if (ev.type === "pty.deleted") {
        const id = String(ev.properties.id ?? "");
        disposePtyInstance(id);
        ptys.value = ptys.value.filter((p) => p.id !== id);
        if (activePtyId.value === id) {
          activePtyId.value = ptys.value[0]?.id ?? null;
          updateVisibleElement();
        }
      }
    }) ?? null;
});

onBeforeUnmount(() => {
  themeObserver?.disconnect();
  unsubGlobal?.();
  for (const id of Array.from(instances.keys())) {
    disposePtyInstance(id);
  }
});
</script>

<template>
  <section
    class="relative flex shrink-0 flex-col border-t border-line bg-sidebar"
    :style="{ height: `${height}px` }"
    aria-label="集成终端"
  >
    <!-- Top Drag Handle -->
    <div
      role="separator"
      tabindex="0"
      aria-orientation="horizontal"
      aria-label="调整终端高度"
      class="group absolute inset-x-0 -top-1 z-20 flex h-2.5 cursor-row-resize touch-none select-none items-center justify-center"
      @pointerdown="onResizePointerDown"
      @pointermove="onResizePointerMove"
      @pointerup="onResizePointerUp"
      @pointercancel="onResizePointerUp"
    >
      <span
        class="h-0.5 w-10 rounded-full transition-colors"
        :class="isResizing ? 'bg-accent' : 'bg-transparent group-hover:bg-line-strong'"
      />
    </div>

    <!-- Terminal Tabs Bar -->
    <div class="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-line/70 px-3">
      <div class="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto custom-scrollbar">
        <span class="mr-1 shrink-0 text-[11px] font-medium uppercase tracking-[0.14em] text-fg-faint">终端</span>

        <div
          v-for="pty in ptys"
          :key="pty.id"
          class="group/tab flex shrink-0 items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] transition-colors"
          :class="activePtyId === pty.id ? 'bg-canvas font-medium text-fg shadow-xs' : 'text-fg-muted hover:bg-hover hover:text-fg'"
        >
          <button
            type="button"
            class="flex items-center gap-1.5"
            @click="activePtyId = pty.id"
          >
            <span
              class="h-1.5 w-1.5 rounded-full"
              :style="{ background: pty.status === 'running' ? 'var(--success)' : 'var(--fg-faint)' }"
            />
            <span class="max-w-[130px] truncate">{{ pty.title || pty.command }}</span>
          </button>
          <button
            type="button"
            class="ml-0.5 rounded px-0.5 text-fg-faint opacity-60 hover:bg-surface hover:text-fg hover:opacity-100"
            title="关闭此终端"
            aria-label="关闭此终端"
            @click.stop="closeTerminal(pty.id)"
          >
            ×
          </button>
        </div>

        <div class="relative shrink-0">
          <button
            type="button"
            class="focus-ring flex h-6 items-center gap-0.5 rounded-lg px-1.5 text-[12px] text-fg-faint transition-colors hover:bg-hover hover:text-fg disabled:opacity-40"
            :disabled="!runtime.ready || creating"
            title="新建终端"
            @click="createTerminal()"
          >
            <span>+</span>
          </button>
          <button
            v-if="shells.length > 1"
            type="button"
            class="focus-ring inline-flex h-6 items-center rounded-lg px-1 text-[10px] text-fg-faint hover:bg-hover hover:text-fg"
            title="选择 Shell 类型"
            @click.stop="shellMenuOpen = !shellMenuOpen"
          >
            ▾
          </button>
          <div
            v-if="shellMenuOpen"
            class="absolute bottom-full left-0 z-30 mb-1 w-44 rounded-xl bg-canvas p-1 text-[12px] dark:bg-[#1a1a19]"
            style="box-shadow: var(--shadow)"
          >
            <button
              v-for="sh in shells"
              :key="sh.path"
              type="button"
              class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-fg-muted hover:bg-hover hover:text-fg"
              @click="createTerminal(sh)"
            >
              <span class="truncate">{{ sh.name }}</span>
              <span v-if="sh.is_default" class="text-[10px] text-fg-faint">默认</span>
            </button>
          </div>
        </div>
      </div>

      <div class="flex shrink-0 items-center gap-1 text-[11px] text-fg-faint">
        <span v-if="activeDirectory" class="hidden max-w-[180px] truncate font-mono sm:inline" :title="activeDirectory">
          {{ activeDirectory.split(/[\\/]/).filter(Boolean).pop() }}
        </span>
        <button
          type="button"
          class="focus-ring rounded-lg px-2 py-1 hover:bg-hover hover:text-fg"
          title="清空终端显示"
          @click="clearActiveTerminal"
        >
          清屏
        </button>
        <button
          type="button"
          class="focus-ring rounded-lg p-1 hover:bg-hover hover:text-fg"
          title="收起终端 (Ctrl+`)"
          aria-label="收起终端"
          @click="emit('close')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </div>

    <div v-if="errorMsg" class="bg-danger-weak px-3 py-1.5 text-[11.5px] text-danger">
      {{ errorMsg }}
    </div>

    <div v-if="!runtime.ready" class="flex flex-1 items-center justify-center text-[12.5px] text-fg-faint">
      等待本机 OpenCode 服务就绪后即可启用集成终端…
    </div>
    <div v-else ref="hostContainerRef" class="min-h-0 flex-1 overflow-hidden p-1.5" />
  </section>
</template>
