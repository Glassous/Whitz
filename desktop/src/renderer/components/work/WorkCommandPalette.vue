<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import type { WorkFindMatch, WorkSymbolMatch } from "@shared/work-types";
import { useRuntimeStore } from "../../stores/runtime";
import { useWorkStore, type WorkCommandPaletteMode } from "../../stores/work";

const emit = defineEmits<{
  insertPath: [string];
  runCommand: [payload: { name: string; args: string }];
  openRemoteSessions: [];
  createWorktree: [];
}>();

const router = useRouter();
const runtime = useRuntimeStore();
const work = useWorkStore();

const dialogRef = ref<HTMLDialogElement | null>(null);
const inputRef = ref<HTMLInputElement | null>(null);

const query = ref("");
const activeIdx = ref(0);
const fileResults = ref<string[]>([]);
const textResults = ref<WorkFindMatch[]>([]);
const symbolResults = ref<WorkSymbolMatch[]>([]);
const searching = ref(false);
let searchTimer: number | null = null;

interface PaletteAction {
  id: string;
  group: string;
  title: string;
  subtitle?: string;
  shortcut?: string;
  run: () => void | Promise<void>;
}

const commandItems = computed<PaletteAction[]>(() => {
  const list: PaletteAction[] = [
    {
      id: "act:new",
      group: "常用操作",
      title: "新建工作区任务",
      subtitle: work.activeWorkspace?.name ?? "当前项目",
      shortcut: "Ctrl+N",
      run: () => void work.create(),
    },
    {
      id: "act:terminal",
      group: "常用操作",
      title: work.terminalOpen ? "收起集成终端" : "打开集成终端 (PTY)",
      shortcut: "Ctrl+`",
      run: () => work.setTerminalOpen(!work.terminalOpen),
    },
    {
      id: "act:inspector",
      group: "常用操作",
      title: work.inspectorOpen ? "收起右侧工作台面板" : "展开右侧工作台面板",
      run: () => work.setInspectorOpen(!work.inspectorOpen),
    },
    {
      id: "act:pick-ws",
      group: "常用操作",
      title: "打开本地项目文件夹",
      run: () => void work.pickWorkspace(),
    },
    {
      id: "act:cli-sync",
      group: "常用操作",
      title: "同步 / 导入本机 OpenCode CLI 会话",
      subtitle: "将终端 opencode 历史无缝导入 Whitz Work",
      run: () => emit("openRemoteSessions"),
    },
    {
      id: "act:worktree",
      group: "常用操作",
      title: "在独立 Git Worktree 中新建并行任务",
      subtitle: "隔离分支目录，互不干扰",
      run: () => emit("createWorktree"),
    },
    {
      id: "act:compact",
      group: "会话操作",
      title: "压缩当前会话上下文 (/compact)",
      run: () => emit("runCommand", { name: "compact", args: "" }),
    },
    {
      id: "act:fork",
      group: "会话操作",
      title: "从当前记录分支新对话 (/fork)",
      run: () => emit("runCommand", { name: "fork", args: "" }),
    },
    {
      id: "act:init",
      group: "会话操作",
      title: "分析项目并生成 AGENTS.md (/init)",
      run: () => emit("runCommand", { name: "init", args: "" }),
    },
    {
      id: "act:share",
      group: "会话操作",
      title: work.current?.conversation.share_url ? "复制/取消当前会话分享链接" : "生成 OpenCode 分享链接",
      run: async () => {
        if (work.current?.conversation.share_url) {
          await navigator.clipboard.writeText(work.current.conversation.share_url).catch(() => undefined);
        } else {
          const url = await work.shareCurrent();
          if (url) await navigator.clipboard.writeText(url).catch(() => undefined);
        }
      },
    },
    {
      id: "act:settings",
      group: "设置",
      title: "打开 Work 设置（模型 / Provider / MCP / 权限）",
      run: () => void router.push({ name: "work-settings" }),
    },
  ];

  // Switch primary agent
  for (const agent of work.primaryAgents) {
    list.push({
      id: `agent:${agent.name}`,
      group: "切换主代理",
      title: `切换代理：${agent.name}`,
      subtitle: agent.description,
      run: () => void work.setSessionPrefs({ agent_name: agent.name }),
    });
  }

  // Switch enabled model
  for (const m of runtime.enabledModels.slice(0, 20)) {
    list.push({
      id: `model:${m.ref}`,
      group: "切换模型",
      title: m.modelID,
      subtitle: m.providerID,
      run: () => void work.setSessionPrefs({ model_ref: m.ref }),
    });
  }

  // Switch recent conversations
  for (const conv of work.conversations.slice(0, 15)) {
    list.push({
      id: `conv:${conv.id}`,
      group: "切换会话",
      title: conv.title,
      subtitle: conv.workspace_path?.split(/[\\/]/).filter(Boolean).pop() ?? undefined,
      run: () => void work.select(conv.id),
    });
  }

  const q = query.value.trim().toLowerCase();
  if (!q) return list;
  return list.filter(
    (item) =>
      item.title.toLowerCase().includes(q) ||
      (item.subtitle ?? "").toLowerCase().includes(q) ||
      item.group.toLowerCase().includes(q),
  );
});

const totalVisibleCount = computed(() => {
  if (work.commandPaletteMode === "commands") return commandItems.value.length;
  if (work.commandPaletteMode === "files") return fileResults.value.length;
  return textResults.value.length + symbolResults.value.length;
});

function setMode(next: WorkCommandPaletteMode) {
  work.commandPaletteMode = next;
  activeIdx.value = 0;
  triggerSearch();
  void nextTick(() => inputRef.value?.focus());
}

function triggerSearch() {
  if (searchTimer) window.clearTimeout(searchTimer);
  const mode = work.commandPaletteMode;
  const q = query.value.trim();
  if (mode === "commands") return;
  searchTimer = window.setTimeout(async () => {
    searching.value = true;
    try {
      if (mode === "files") {
        fileResults.value = (await window.whitzDesktop?.workspace.searchFiles(q)) ?? [];
      } else if (mode === "search") {
        if (!q) {
          textResults.value = [];
          symbolResults.value = [];
        } else {
          const [texts, syms] = await Promise.all([
            window.whitzDesktop?.workspace.findText(q, work.activeWorkspace?.path).catch(() => []) ?? [],
            window.whitzDesktop?.workspace.findSymbols(q, work.activeWorkspace?.path).catch(() => []) ?? [],
          ]);
          textResults.value = texts;
          symbolResults.value = syms;
        }
      }
      activeIdx.value = 0;
    } finally {
      searching.value = false;
    }
  }, 110);
}

function close() {
  work.closeCommandPalette();
}

function executeAtIndex(idx: number, shiftKey = false) {
  if (work.commandPaletteMode === "commands") {
    const item = commandItems.value[idx];
    if (!item) return;
    close();
    void item.run();
    return;
  }
  if (work.commandPaletteMode === "files") {
    const file = fileResults.value[idx];
    if (!file) return;
    close();
    if (shiftKey) emit("insertPath", file);
    else void work.openFilePreview(file);
    return;
  }
  const symLen = symbolResults.value.length;
  if (idx < symLen) {
    const sym = symbolResults.value[idx];
    if (sym) {
      close();
      void work.openFilePreview(sym.path);
    }
  } else {
    const match = textResults.value[idx - symLen];
    if (match) {
      close();
      void work.openFilePreview(match.path);
    }
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (totalVisibleCount.value > 0) activeIdx.value = (activeIdx.value + 1) % totalVisibleCount.value;
    return;
  }
  if (e.key === "ArrowUp") {
    e.preventDefault();
    if (totalVisibleCount.value > 0) {
      activeIdx.value = (activeIdx.value - 1 + totalVisibleCount.value) % totalVisibleCount.value;
    }
    return;
  }
  if (e.key === "Enter" && !e.isComposing) {
    e.preventDefault();
    executeAtIndex(activeIdx.value, e.shiftKey);
    return;
  }
  if (e.key === "Tab") {
    e.preventDefault();
    const order: WorkCommandPaletteMode[] = ["commands", "files", "search"];
    const next = order[(order.indexOf(work.commandPaletteMode) + 1) % order.length];
    setMode(next);
  }
}

function onDialogClose() {
  const dlg = dialogRef.value;
  if (dlg) dlg.returnValue = "";
  if (work.commandPaletteOpen) work.closeCommandPalette();
}

let pointerDownOutside = false;
function isOutsideDialog(e: PointerEvent, dlg: HTMLDialogElement): boolean {
  const r = dlg.getBoundingClientRect();
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
}
function onDialogPointerDown(e: PointerEvent) {
  const dlg = dialogRef.value;
  if (!dlg || "closedBy" in HTMLDialogElement.prototype) return;
  pointerDownOutside = isOutsideDialog(e, dlg);
}
function onDialogPointerUp(e: PointerEvent) {
  const dlg = dialogRef.value;
  if (!dlg || "closedBy" in HTMLDialogElement.prototype) return;
  if (pointerDownOutside && isOutsideDialog(e, dlg)) dlg.close();
  pointerDownOutside = false;
}

watch(
  () => work.commandPaletteOpen,
  async (open) => {
    const dlg = dialogRef.value;
    if (!dlg) return;
    if (open) {
      query.value = "";
      activeIdx.value = 0;
      if (!dlg.open) dlg.showModal();
      triggerSearch();
      await nextTick();
      inputRef.value?.focus();
    } else if (dlg.open) {
      dlg.close();
    }
  },
);

watch(query, () => {
  activeIdx.value = 0;
  triggerSearch();
});

onMounted(() => {
  if (work.commandPaletteOpen && dialogRef.value && !dialogRef.value.open) {
    dialogRef.value.showModal();
  }
});

onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer);
});
</script>

<template>
  <dialog
    ref="dialogRef"
    v-bind="{ closedby: 'any' }"
    aria-label="Work 命令与快速检索面板"
    class="work-native-dialog m-auto mt-[10vh] max-h-[72vh] w-[min(640px,92vw)] flex-col overflow-hidden rounded-2xl border border-line bg-canvas p-0 text-fg shadow-2xl"
    @close="onDialogClose"
    @pointerdown="onDialogPointerDown"
    @pointerup="onDialogPointerUp"
  >
    <!-- Mode Tabs + Search Bar -->
    <div class="shrink-0 border-b border-line p-3">
      <div class="mb-2 flex items-center justify-between gap-2">
        <div class="flex items-center gap-1 rounded-xl bg-surface p-0.5 text-[12px]">
          <button
            type="button"
            class="rounded-lg px-2.5 py-1 transition-colors"
            :class="work.commandPaletteMode === 'commands' ? 'bg-canvas font-medium text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
            @click="setMode('commands')"
          >
            命令 (Ctrl+K)
          </button>
          <button
            type="button"
            class="rounded-lg px-2.5 py-1 transition-colors"
            :class="work.commandPaletteMode === 'files' ? 'bg-canvas font-medium text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
            @click="setMode('files')"
          >
            文件 (Ctrl+P)
          </button>
          <button
            type="button"
            class="rounded-lg px-2.5 py-1 transition-colors"
            :class="work.commandPaletteMode === 'search' ? 'bg-canvas font-medium text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
            @click="setMode('search')"
          >
            代码/符号 (Ctrl+Shift+F)
          </button>
        </div>

        <button
          type="button"
          class="rounded-lg px-2 py-1 text-[11.5px] text-fg-faint hover:bg-hover hover:text-fg"
          aria-label="关闭命令面板"
          @click="close"
        >
          Esc
        </button>
      </div>

      <input
        ref="inputRef"
        v-model="query"
        type="search"
        autofocus
        :placeholder="
          work.commandPaletteMode === 'commands'
            ? '搜索命令、会话、模型或主代理… (Tab 切换页签)'
            : work.commandPaletteMode === 'files'
              ? '输入文件名快速定位… (Enter 预览，Shift+Enter @引用)'
              : '输入正则或符号名进行 ripgrep / LSP 检索…'
        "
        class="focus-ring w-full rounded-xl bg-surface px-3.5 py-2.5 text-[13.5px] text-fg outline-none placeholder:text-fg-faint"
        @keydown="onKeydown"
      />
    </div>

    <!-- Results List -->
    <div class="min-h-0 flex-1 overflow-y-auto custom-scrollbar p-2">
      <p v-if="searching" class="py-8 text-center text-[12.5px] text-fg-faint">检索中…</p>

      <!-- Commands Mode -->
      <template v-else-if="work.commandPaletteMode === 'commands'">
        <p v-if="!commandItems.length" class="py-8 text-center text-[12.5px] text-fg-faint">没有匹配的命令或会话</p>
        <button
          v-for="(item, idx) in commandItems"
          :key="item.id"
          type="button"
          class="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-[13px] transition-colors"
          :class="idx === activeIdx ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @mouseenter="activeIdx = idx"
          @click="executeAtIndex(idx)"
        >
          <div class="min-w-0 flex-1">
            <span class="font-medium text-fg">{{ item.title }}</span>
            <span v-if="item.subtitle" class="ml-2 text-[11.5px] text-fg-faint">{{ item.subtitle }}</span>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <span class="rounded bg-surface px-1.5 py-0.5 text-[10.5px] text-fg-faint">{{ item.group }}</span>
            <kbd v-if="item.shortcut" class="rounded bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted">
              {{ item.shortcut }}
            </kbd>
          </div>
        </button>
      </template>

      <!-- Files Mode -->
      <template v-else-if="work.commandPaletteMode === 'files'">
        <p v-if="!fileResults.length" class="py-8 text-center text-[12.5px] text-fg-faint">
          {{ work.activeWorkspace ? "没有匹配的工作区文件" : "请先选择本地项目文件夹" }}
        </p>
        <div
          v-for="(file, idx) in fileResults"
          :key="file"
          class="flex items-center justify-between gap-2 rounded-xl px-3 py-2 text-[12.5px] transition-colors"
          :class="idx === activeIdx ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @mouseenter="activeIdx = idx"
        >
          <button type="button" class="min-w-0 flex-1 truncate text-left font-mono" @click="executeAtIndex(idx, false)">
            {{ file }}
          </button>
          <button
            type="button"
            class="shrink-0 rounded-lg bg-surface px-2 py-0.5 text-[11px] text-fg-faint hover:text-fg"
            @click="executeAtIndex(idx, true)"
          >
            @引用
          </button>
        </div>
      </template>

      <!-- Fulltext & Symbols Mode -->
      <template v-else>
        <p v-if="!query.trim()" class="py-8 text-center text-[12.5px] text-fg-faint">输入关键字搜索工作区代码内容与 LSP 符号</p>
        <p v-else-if="!symbolResults.length && !textResults.length" class="py-8 text-center text-[12.5px] text-fg-faint">
          未找到匹配的代码片段或符号
        </p>
        <template v-else>
          <template v-if="symbolResults.length">
            <p class="px-3 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-fg-faint">LSP 符号</p>
            <button
              v-for="(sym, sIdx) in symbolResults"
              :key="`sym-${sym.path}-${sym.line}-${sym.name}`"
              type="button"
              class="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-1.5 text-left text-[12.5px]"
              :class="sIdx === activeIdx ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
              @mouseenter="activeIdx = sIdx"
              @click="executeAtIndex(sIdx)"
            >
              <span class="font-mono font-medium text-fg">{{ sym.name }}</span>
              <span class="truncate font-mono text-[11px] text-fg-faint">{{ sym.path }}:{{ sym.line }}</span>
            </button>
          </template>
          <template v-if="textResults.length">
            <p class="mt-2 px-3 py-1 text-[10.5px] font-semibold uppercase tracking-wider text-fg-faint">全文命中</p>
            <button
              v-for="(m, mIdx) in textResults"
              :key="`txt-${m.path}-${m.line_number}-${mIdx}`"
              type="button"
              class="flex w-full flex-col rounded-xl px-3 py-1.5 text-left"
              :class="symbolResults.length + mIdx === activeIdx ? 'bg-active text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
              @mouseenter="activeIdx = symbolResults.length + mIdx"
              @click="executeAtIndex(symbolResults.length + mIdx)"
            >
              <span class="font-mono text-[11px] text-fg-faint">{{ m.path }}:{{ m.line_number }}</span>
              <span class="mt-0.5 truncate font-mono text-[12px] text-fg">{{ m.lines }}</span>
            </button>
          </template>
        </template>
      </template>
    </div>
  </dialog>
</template>
