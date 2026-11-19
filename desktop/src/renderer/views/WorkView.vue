<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import type { WorkAttachment } from "@shared/work-types";
import { useDesktopStore } from "../stores/desktop";
import { useRuntimeStore } from "../stores/runtime";
import { useWorkStore } from "../stores/work";
import BaseButton from "@web/components/ui/BaseButton.vue";
import WorkSidebar from "../components/work/WorkSidebar.vue";
import WorkMessageList from "../components/work/WorkMessageList.vue";
import WorkComposer from "../components/work/WorkComposer.vue";
import WorkInspectorPanel from "../components/work/WorkInspectorPanel.vue";
import ApprovalSheet from "../components/work/ApprovalSheet.vue";

const router = useRouter();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const work = useWorkStore();

const sidebarOpen = ref(false);
const drawerDragProgress = ref<number | null>(null);
const composerRef = ref<InstanceType<typeof WorkComposer> | null>(null);

const PANEL_WIDTH_KEY = "whitz_work_panel_width";
const DEFAULT_PANEL_WIDTH = 360;
const MIN_PANEL_WIDTH = 300;

function maxPanelWidth(): number {
  if (typeof window === "undefined") return 820;
  return Math.max(MIN_PANEL_WIDTH, Math.floor(Math.min(820, window.innerWidth * 0.56)));
}

function clampPanelWidth(w: number): number {
  return Math.round(Math.max(MIN_PANEL_WIDTH, Math.min(maxPanelWidth(), w)));
}

function loadPanelWidth(): number {
  if (typeof window === "undefined") return DEFAULT_PANEL_WIDTH;
  try {
    const raw = window.localStorage.getItem(PANEL_WIDTH_KEY);
    const parsed = raw ? Number(raw) : DEFAULT_PANEL_WIDTH;
    return Number.isFinite(parsed) && parsed > 0 ? clampPanelWidth(parsed) : clampPanelWidth(DEFAULT_PANEL_WIDTH);
  } catch {
    return DEFAULT_PANEL_WIDTH;
  }
}

function savePanelWidth(width: number) {
  try {
    window.localStorage.setItem(PANEL_WIDTH_KEY, String(width));
  } catch {
    /* ignore */
  }
}

const panelWidth = ref<number>(loadPanelWidth());
const isResizingPanel = ref(false);
let resizeStartX = 0;
let resizeStartWidth = DEFAULT_PANEL_WIDTH;

function onPanelResizePointerDown(e: PointerEvent) {
  if (!work.inspectorOpen) return;
  const target = e.currentTarget as HTMLElement;
  target.setPointerCapture(e.pointerId);
  isResizingPanel.value = true;
  resizeStartX = e.clientX;
  resizeStartWidth = panelWidth.value;
}

function onPanelResizePointerMove(e: PointerEvent) {
  if (!isResizingPanel.value) return;
  const delta = resizeStartX - e.clientX;
  panelWidth.value = clampPanelWidth(resizeStartWidth + delta);
}

function onPanelResizePointerUp(e: PointerEvent) {
  if (!isResizingPanel.value) return;
  isResizingPanel.value = false;
  const target = e.currentTarget as HTMLElement;
  if (target.hasPointerCapture(e.pointerId)) {
    target.releasePointerCapture(e.pointerId);
  }
  savePanelWidth(panelWidth.value);
}

function onWindowResize() {
  panelWidth.value = clampPanelWidth(panelWidth.value);
}

function onSidebarToggleClick() {
  if (window.innerWidth >= 768) {
    desktop.toggleSidebarCollapsed();
  } else {
    sidebarOpen.value = true;
  }
}

function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "b") {
    e.preventDefault();
    onSidebarToggleClick();
  }
}

onMounted(async () => {
  desktop.syncSidebarCollapsedFromStorage();
  window.addEventListener("keydown", onGlobalKeydown);
  window.addEventListener("resize", onWindowResize);
  await work.loadWorkspaceState();
  await work.loadList();
  if (!work.current && work.conversations[0]) await work.select(work.conversations[0].id);
  if (runtime.ready) void work.loadSkills();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
  window.removeEventListener("resize", onWindowResize);
});

watch(
  () => runtime.ready,
  (ready) => {
    if (ready) void work.loadSkills();
  },
);

const title = computed(() => work.current?.conversation.title ?? "本地工作台");
const blockedReason = computed(() => {
  if (!runtime.installed) return "尚未检测到本机 OpenCode CLI";
  if (runtime.status?.state === "disabled") return "Whitz Work 已被远程策略禁用";
  if (runtime.settings?.model.mode === "builtin" && !desktop.loggedIn) {
    return "「Whitz 内置」模型需要登录账号，请在 Work 设置中改用本机 OpenCode 模型";
  }
  return null;
});
const disabled = computed(() => Boolean(blockedReason.value));
const isQuotaError = computed(() => Boolean(work.error && (work.error.includes("402") || work.error.includes("额度"))));

async function send(payload: { content: string; skillNames: string[]; attachments: WorkAttachment[] }) {
  await work.send(payload.content, {
    skillNames: payload.skillNames,
    attachments: payload.attachments,
  });
}

async function steer(content: string) {
  await work.steer(content);
}

const runtimeStatusLabel = computed(() => {
  if (!runtime.installed) return "OpenCode 未检测";
  const state = runtime.status?.state;
  if (state === "ready") return "OpenCode 就绪";
  if (state === "starting") return "OpenCode 启动中";
  if (state === "error") return "OpenCode 重连中";
  if (state === "disabled") return "OpenCode 已禁用";
  return "OpenCode 待命";
});

const runtimeStatusColor = computed(() => {
  if (runtime.ready) return "var(--success)";
  const state = runtime.status?.state;
  if (state === "error") return "var(--danger)";
  if (state === "starting") return "var(--warning)";
  return "var(--fg-faint)";
});

function insertPathToComposer(relPath: string) {
  composerRef.value?.insertPath(relPath);
}

async function exportConversation() {
  if (!work.current) return;
  const result = await window.whitzDesktop?.work.export(work.current.conversation.id);
  if (result?.path) window.alert(`已导出到：${result.path}`);
}
</script>

<template>
  <div v-if="!desktop.workEnabled" class="work-glow flex h-full items-center justify-center px-8">
    <section class="max-w-[520px] rounded-3xl border border-line bg-canvas/85 p-8 shadow-[var(--shadow)]">
      <p class="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-faint">Whitz Work</p>
      <h1 class="mt-3 text-[22px] font-semibold text-fg">该模式当前不可用</h1>
      <p class="mt-2 text-[13.5px] leading-relaxed text-fg-muted">
        {{ desktop.policy?.disabled_reason || "服务端策略已关闭 Work 模式。本地智能体不会启动，你仍可以正常使用 Chat。" }}
      </p>
      <div class="mt-5 flex gap-2.5">
        <BaseButton @click="router.push({ name: 'chat-gate' })">使用 Chat</BaseButton>
        <BaseButton variant="secondary" @click="router.push({ name: 'work-settings' })">查看策略</BaseButton>
      </div>
    </section>
  </div>

  <div v-else class="flex h-full min-h-0 overflow-hidden bg-canvas">
    <div
      v-if="sidebarOpen"
      class="fixed inset-0 z-30 bg-black/40 md:hidden"
      :style="drawerDragProgress !== null ? { opacity: drawerDragProgress, transition: 'none' } : undefined"
      @click="sidebarOpen = false"
    />

    <WorkSidebar
      :open="sidebarOpen"
      @close="sidebarOpen = false"
      @drag-progress="drawerDragProgress = $event"
    />

    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Top Header -->
      <header class="flex h-13 shrink-0 items-center justify-between gap-2.5 border-b border-line px-3.5">
        <div class="flex min-w-0 flex-1 items-center gap-2.5">
          <button
            type="button"
            class="focus-ring flex h-9.5 w-9.5 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
            :aria-label="desktop.sidebarCollapsed ? '展开侧栏' : '切换侧栏'"
            :title="desktop.sidebarCollapsed ? '展开侧栏 (Ctrl+B)' : '收起侧栏 (Ctrl+B)'"
            @click="onSidebarToggleClick"
          >
            <svg class="h-[20px] w-[20px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" d="M4 8.5h16M4 15.5h10" />
            </svg>
          </button>

          <h2 class="truncate text-[14.5px] font-semibold text-fg">{{ title }}</h2>

          <button
            type="button"
            class="focus-ring hidden shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface/60 px-2.5 py-0.5 text-[11px] text-fg-muted transition-colors hover:border-line-strong hover:text-fg sm:inline-flex"
            :title="work.activeWorkspace?.path || '点击选择本地工作区'"
            @click="work.pickWorkspace()"
          >
            <span
              class="h-1.5 w-1.5 rounded-full"
              :style="{ background: work.activeWorkspace ? 'var(--work-accent)' : 'var(--fg-faint)' }"
            />
            <span class="max-w-[160px] truncate">
              {{ work.activeWorkspace ? work.activeWorkspace.name : "选择工作区" }}
            </span>
          </button>

          <span
            class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface/45 px-2.5 py-0.5 text-[11px]"
            :style="{ color: runtimeStatusColor }"
            :title="runtime.status?.detail || runtime.status?.exe_path || runtimeStatusLabel"
          >
            <span
              class="h-1.5 w-1.5 rounded-full"
              :class="{ 'work-dot-live': runtime.ready }"
              :style="{ background: runtimeStatusColor }"
            />
            {{ runtimeStatusLabel }}
          </span>
        </div>

        <div class="flex shrink-0 items-center gap-1.5">
          <BaseButton v-if="work.current" size="sm" variant="ghost" @click="exportConversation">导出</BaseButton>
          <BaseButton size="sm" variant="ghost" @click="router.push({ name: 'work-settings' })">设置</BaseButton>
          <button
            type="button"
            class="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
            :aria-label="work.inspectorOpen ? '收起工作区面板' : '展开工作区面板'"
            :title="work.inspectorOpen ? '收起工作区面板' : '展开工作区面板'"
            @click="work.setInspectorOpen(!work.inspectorOpen)"
          >
            <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 5h18v14H3zM15 5v14" />
            </svg>
          </button>
        </div>
      </header>

      <!-- Not Installed Gate -->
      <div v-if="!runtime.installed" class="flex min-h-0 flex-1 items-center justify-center px-8">
        <section class="max-w-[560px] rounded-2xl border border-line bg-canvas p-7 text-center">
          <h3 class="text-[17px] font-semibold text-fg">未检测到本机 OpenCode CLI</h3>
          <p class="mt-2 text-[13px] leading-relaxed text-fg-muted">
            Whitz Work 直接调用并复用你电脑上已有的 OpenCode（本应用不内置安装器）。请先安装 OpenCode 或手动指定已有可执行文件。
          </p>
          <div class="mt-5 flex flex-wrap justify-center gap-2.5">
            <BaseButton :loading="runtime.busy" @click="runtime.redetect()">重新检测</BaseButton>
            <BaseButton variant="secondary" @click="router.push({ name: 'work-setup' })">查看安装指引</BaseButton>
            <BaseButton variant="ghost" @click="router.push({ name: 'work-settings' })">指定已有路径</BaseButton>
          </div>
        </section>
      </div>

      <template v-else>
        <div
          v-if="work.error"
          class="flex items-center justify-between gap-3 border-b border-line bg-danger-weak/50 px-5 py-2 text-[12px] text-danger"
        >
          <span class="min-w-0 flex-1">{{ work.error }}</span>
          <div class="flex shrink-0 items-center gap-2">
            <button
              v-if="isQuotaError"
              type="button"
              class="rounded-md bg-canvas px-2 py-0.5 text-[11px] font-medium text-fg hover:bg-hover"
              @click="router.push({ name: 'work-settings' })"
            >
              切换自带 Key
            </button>
            <button type="button" class="text-[11px] hover:opacity-75" @click="work.error = null">关闭</button>
          </div>
        </div>

        <WorkMessageList
          :messages="work.messages"
          :active-assistant-id="work.activeAssistantId"
          :streaming="work.streaming"
          @open-file="work.openFilePreview($event)"
        />

        <WorkComposer
          ref="composerRef"
          :streaming="work.streaming"
          :sending="work.sending"
          :disabled="disabled"
          :disabled-reason="blockedReason"
          @send="send"
          @steer="steer"
          @stop="work.stop()"
        />
      </template>
    </div>

    <!-- Resizable Workbench Inspector Panel -->
    <div
      v-if="work.inspectorOpen"
      class="relative hidden h-full shrink-0 lg:flex"
      :style="{ width: `${panelWidth}px` }"
    >
      <div
        role="separator"
        tabindex="0"
        aria-orientation="vertical"
        aria-label="调整工作区面板宽度"
        class="group/sep absolute inset-y-0 left-0 z-20 w-1.5 -translate-x-1/2 cursor-col-resize"
        @pointerdown="onPanelResizePointerDown"
        @pointermove="onPanelResizePointerMove"
        @pointerup="onPanelResizePointerUp"
        @pointercancel="onPanelResizePointerUp"
      >
        <div class="mx-auto h-full w-px bg-transparent transition-colors group-hover/sep:bg-[var(--work-accent)]" />
      </div>

      <WorkInspectorPanel
        @insert-path="insertPathToComposer"
        @close="work.setInspectorOpen(false)"
      />
    </div>
  </div>

  <ApprovalSheet
    v-if="work.pendingControl"
    :kind="work.pendingControl.kind"
    :tool="work.pendingControl.tool"
    :preview="work.pendingControl.preview"
    :choices="work.pendingControl.choices"
    @approve="work.approve"
    @clarify="work.clarify"
  />
</template>
