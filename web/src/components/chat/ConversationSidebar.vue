<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { streamSSE } from "../../api/sse";
import type { Conversation } from "../../types";
import { useAuthStore } from "../../stores/auth";
import { sortConversations } from "../../stores/conversations";
import { useCreditsStore } from "../../stores/credits";
import { usePostsStore } from "../../stores/posts";
import { useTheme, type ThemePreference } from "../../lib/theme";
import { isDesktopHost } from "../../host";
import { isDesktopShell } from "../../host/chrome";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import BaseInput from "../ui/BaseInput.vue";
import AppIcon from "../ui/AppIcon.vue";

const props = defineProps<{
  mainConversation: Conversation | null;
  sideConversations: Conversation[];
  currentId: string | null;
  activeView: "chat" | "posts" | "library" | "schedules";
  loading?: boolean;
  open?: boolean;
  collapsed?: boolean;
  renameAction?: (id: string, title: string) => Promise<void>;
  deleteAction?: (id: string) => Promise<void>;
}>();

const emit = defineEmits<{
  select: [string];
  "select-main": [];
  "create-side": [];
  "switch-view": ["chat" | "posts" | "library" | "schedules"];
  "toggle-collapse": [];
  rename: [string, string];
  pin: [string, boolean];
  delete: [string];
  close: [];
  "open-search": [];
  "drag-progress": [number | null];
}>();

const router = useRouter();
const auth = useAuthStore();
const credits = useCreditsStore();
const postsStore = usePostsStore();
const { preference, set: setTheme } = useTheme();

const themeOptions: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

// Track desktop breakpoint so mobile drawer always renders full dual-column layout.
const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;
function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
  if (!e.matches) hideTooltip();
}

const isSecondaryCollapsed = computed(() => Boolean(props.collapsed && isDesktop.value));
const isMobileDrawer = computed(() => !isDesktop.value);
const inDesktop = computed(() => isDesktopShell() || isDesktopHost());

// Assistant identity for the pinned Main Chat entry
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
const assistantAvatarUrl = computed(() => auth.user?.assistant_avatar_url ?? null);
const assistantAvatarFailed = ref(false);
watch(assistantAvatarUrl, () => {
  assistantAvatarFailed.value = false;
});

// 1:1 finger-following left-swipe to close on mobile
const asideRef = ref<HTMLElement | null>(null);
const isSwiping = ref(false);
const dragOffsetX = ref(0);
let swipeStartX = 0;
let swipeStartY = 0;
let swipeStartTime = 0;
let swipeLocked: "horizontal" | "vertical" | null = null;
let drawerWidth = 312;

function resetSwipe() {
  isSwiping.value = false;
  dragOffsetX.value = 0;
  swipeLocked = null;
  emit("drag-progress", null);
}

function onTouchStart(e: TouchEvent) {
  if (isDesktop.value || !props.open || e.touches.length !== 1) return;
  const t = e.touches[0];
  swipeStartX = t.clientX;
  swipeStartY = t.clientY;
  swipeStartTime = performance.now();
  swipeLocked = null;
  drawerWidth = asideRef.value?.offsetWidth || 312;
}

function onTouchMove(e: TouchEvent) {
  if (isDesktop.value || !props.open || e.touches.length !== 1) return;
  const t = e.touches[0];
  const dx = t.clientX - swipeStartX;
  const dy = t.clientY - swipeStartY;

  if (!swipeLocked) {
    if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 6) {
      swipeLocked = "vertical";
      return;
    }
    if (dx < -6 && Math.abs(dx) > Math.abs(dy)) {
      swipeLocked = "horizontal";
      isSwiping.value = true;
    } else {
      return;
    }
  }

  if (swipeLocked === "horizontal") {
    if (e.cancelable) e.preventDefault();
    const clamped = Math.max(-drawerWidth, Math.min(0, dx));
    dragOffsetX.value = clamped;
    emit("drag-progress", Math.max(0, Math.min(1, 1 + clamped / drawerWidth)));
  }
}

function onTouchEnd(e: TouchEvent) {
  if (!isSwiping.value) {
    swipeLocked = null;
    return;
  }
  const elapsed = Math.max(1, performance.now() - swipeStartTime);
  const endX = e.changedTouches[0]?.clientX ?? swipeStartX;
  const velocity = (endX - swipeStartX) / elapsed;
  const shouldClose = dragOffsetX.value < -drawerWidth * 0.3 || velocity < -0.45;
  resetSwipe();
  if (shouldClose) {
    emit("close");
  }
}

function onDrawerKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && !isDesktop.value && props.open) {
    e.stopPropagation();
    emit("close");
  }
}

watch(
  () => props.open,
  (val) => {
    if (!val) resetSwipe();
  },
);

const drawerStyle = computed(() => {
  if (!isSwiping.value || isDesktop.value) return undefined;
  return {
    translate: `${dragOffsetX.value}px 0px`,
    transition: "none",
  };
});

// Quick settings card (opened by clicking bottom avatar in primary rail)
const quickCardOpen = ref(false);
const avatarBtnRef = ref<HTMLElement | null>(null);
const quickCardStyle = ref<{ left: string; bottom: string }>({ left: "72px", bottom: "16px" });

function updateQuickCardPosition() {
  const rect = avatarBtnRef.value?.getBoundingClientRect();
  if (!rect) return;
  const left = Math.min(window.innerWidth - 304, rect.right + 12);
  const bottom = Math.max(12, window.innerHeight - rect.bottom);
  quickCardStyle.value = {
    left: `${Math.max(12, left)}px`,
    bottom: `${bottom}px`,
  };
}

function toggleQuickCard() {
  quickCardOpen.value = !quickCardOpen.value;
  if (quickCardOpen.value) {
    hideTooltip();
    updateQuickCardPosition();
    void credits.fetch();
  }
}

function goToSettings() {
  quickCardOpen.value = false;
  hideTooltip();
  emit("close");
  void router.push("/settings");
}

// Floating tooltip for primary icon rail
const tooltip = ref<{ title: string; sub?: string; top: number; left: number } | null>(null);

function showTooltip(event: MouseEvent | FocusEvent, title: string, sub?: string) {
  if (!isDesktop.value) return;
  const target = event.currentTarget as HTMLElement | null;
  if (!target) return;
  const rect = target.getBoundingClientRect();
  tooltip.value = {
    title,
    sub,
    top: rect.top + rect.height / 2,
    left: rect.right + 10,
  };
}

function hideTooltip() {
  tooltip.value = null;
}

function onClickChatRail() {
  hideTooltip();
  quickCardOpen.value = false;
  if (props.activeView !== "chat") {
    emit("switch-view", "chat");
  } else if (isSecondaryCollapsed.value) {
    emit("toggle-collapse");
  }
}

function onClickSearchRail() {
  hideTooltip();
  quickCardOpen.value = false;
  emit("open-search");
  emit("close");
}

function onClickLibraryRail() {
  hideTooltip();
  quickCardOpen.value = false;
  emit("switch-view", "library");
  emit("close");
}

function onClickPostsRail() {
  hideTooltip();
  quickCardOpen.value = false;
  postsStore.markRead();
  emit("switch-view", "posts");
  emit("close");
}

function onClickSchedulesRail() {
  hideTooltip();
  quickCardOpen.value = false;
  emit("switch-view", "schedules");
  emit("close");
}

const tierBadgeClass = computed(() => {
  if (credits.tier === "pro") return "bg-primary text-primary-fg";
  if (credits.tier === "plus") return "bg-active text-fg";
  return "bg-surface text-fg-muted";
});

function quotaTone(percent: number): string {
  if (percent <= 15) return "bg-danger";
  if (percent <= 35) return "bg-warning";
  return "bg-accent";
}

function fmtReset(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

const renameTarget = ref<Conversation | null>(null);
const renameText = ref("");
const renameError = ref<string | null>(null);
const renameGenerating = ref(false);
const renameSaving = ref(false);
let titleController: AbortController | null = null;
const deleteTarget = ref<Conversation | null>(null);
const deleteSaving = ref(false);
const deleteError = ref<string | null>(null);
const openMenuId = ref<string | null>(null);

const sortedSides = computed(() => sortConversations(props.sideConversations));
const pinnedSides = computed(() => sortedSides.value.filter((c) => c.is_pinned));
const recentSides = computed(() => sortedSides.value.filter((c) => !c.is_pinned));

const sideSections = computed(() => {
  if (!pinnedSides.value.length) {
    return recentSides.value.length ? [{ key: "all", label: "", items: recentSides.value }] : [];
  }
  const sections: { key: string; label: string; items: Conversation[] }[] = [
    { key: "pinned", label: "置顶旁聊", items: pinnedSides.value },
  ];
  if (recentSides.value.length) {
    sections.push({ key: "recent", label: "最近旁聊", items: recentSides.value });
  }
  return sections;
});

const avatarLoadFailed = ref(false);
watch(
  () => auth.user?.avatar_url,
  () => {
    avatarLoadFailed.value = false;
  },
);

const initials = computed(() => {
  const name = auth.user?.display_name?.trim();
  if (name) return Array.from(name)[0]?.toUpperCase() ?? "U";
  return auth.user?.email?.slice(0, 1).toUpperCase() ?? "U";
});

function selectMain() {
  openMenuId.value = null;
  quickCardOpen.value = false;
  hideTooltip();
  emit("select-main");
  emit("close");
}

function selectSide(id: string) {
  openMenuId.value = null;
  quickCardOpen.value = false;
  hideTooltip();
  emit("select", id);
  emit("close");
}

function createSide() {
  openMenuId.value = null;
  quickCardOpen.value = false;
  hideTooltip();
  emit("create-side");
  emit("close");
}

function toggleMenu(c: Conversation) {
  openMenuId.value = openMenuId.value === c.id ? null : c.id;
}

function togglePin(c: Conversation) {
  openMenuId.value = null;
  emit("pin", c.id, !c.is_pinned);
}

function closePopovers() {
  openMenuId.value = null;
  quickCardOpen.value = false;
}

function onEscapeKey(e: KeyboardEvent) {
  if (e.key === "Escape") {
    if (quickCardOpen.value) quickCardOpen.value = false;
    if (openMenuId.value) openMenuId.value = null;
  }
}

onMounted(() => {
  document.addEventListener("click", closePopovers);
  document.addEventListener("keydown", onEscapeKey);
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  void credits.fetch();
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closePopovers);
  document.removeEventListener("keydown", onEscapeKey);
  mediaQuery?.removeEventListener("change", onMediaChange);
  stopTitleGeneration();
});

function stopTitleGeneration() {
  titleController?.abort();
  titleController = null;
  renameGenerating.value = false;
}

function openRename(c: Conversation) {
  openMenuId.value = null;
  stopTitleGeneration();
  renameError.value = null;
  renameTarget.value = c;
  renameText.value = c.title;
}

function closeRename() {
  if (renameSaving.value) return;
  stopTitleGeneration();
  renameTarget.value = null;
  renameText.value = "";
  renameError.value = null;
}

async function generateRenameTitle() {
  if (!renameTarget.value || renameGenerating.value) return;
  const id = renameTarget.value.id;
  renameError.value = null;
  renameText.value = "";
  renameGenerating.value = true;
  const controller = new AbortController();
  titleController = controller;
  try {
    for await (const ev of streamSSE(`/conversations/${id}/title/generate`, {}, controller.signal)) {
      if (controller.signal.aborted) break;
      if (ev.event === "title.delta") {
        const text = typeof ev.data.text === "string" ? ev.data.text : "";
        if (text) renameText.value += text;
      } else if (ev.event === "title.done") {
        const title = typeof ev.data.title === "string" ? ev.data.title.trim() : "";
        if (title) renameText.value = title;
        break;
      } else if (ev.event === "error") {
        renameError.value = typeof ev.data.detail === "string" ? ev.data.detail : "标题生成失败";
        break;
      }
    }
  } catch (e: any) {
    if (!controller.signal.aborted) {
      renameError.value = e?.detail?.detail ?? e?.message ?? "标题生成失败";
    }
  } finally {
    if (titleController === controller) {
      titleController = null;
      renameGenerating.value = false;
    }
  }
}

async function confirmRename() {
  if (renameGenerating.value || renameSaving.value) return;
  const target = renameTarget.value;
  const trimmed = renameText.value.trim();
  if (!target || !trimmed) {
    closeRename();
    return;
  }
  if (props.renameAction) {
    renameSaving.value = true;
    renameError.value = null;
    try {
      await props.renameAction(target.id, trimmed);
      renameSaving.value = false;
      closeRename();
    } catch (e: any) {
      renameError.value = e?.detail?.detail ?? e?.message ?? "重命名失败，请重试";
      renameSaving.value = false;
    }
    return;
  }
  emit("rename", target.id, trimmed);
  closeRename();
}

function askDelete(c: Conversation) {
  openMenuId.value = null;
  deleteError.value = null;
  deleteTarget.value = c;
}

function closeDelete() {
  if (deleteSaving.value) return;
  deleteTarget.value = null;
  deleteError.value = null;
}

async function confirmDelete() {
  if (deleteSaving.value || !deleteTarget.value) return;
  const target = deleteTarget.value;
  if (props.deleteAction) {
    deleteSaving.value = true;
    deleteError.value = null;
    try {
      await props.deleteAction(target.id);
      deleteSaving.value = false;
      deleteTarget.value = null;
    } catch (e: any) {
      deleteError.value = e?.detail?.detail ?? e?.message ?? "删除失败，请重试";
      deleteSaving.value = false;
    }
    return;
  }
  emit("delete", target.id);
  deleteTarget.value = null;
}

const ACTIVE_RUN_STATUSES = new Set([
  "starting",
  "running",
  "waiting",
  "waiting_for_approval",
  "waiting_for_clarify",
]);

function isRunning(c: Conversation | null | undefined): boolean {
  return Boolean(c?.active_run_status && ACTIVE_RUN_STATUSES.has(c.active_run_status));
}

function isScheduledSide(c: Conversation | null | undefined): boolean {
  if (!c || c.kind === "main") return false;
  return Boolean(c.is_scheduled || (c.title || "").startsWith("[定时]"));
}

function displaySideTitle(c: Conversation): string {
  const raw = c.title || "新旁聊";
  if (!isScheduledSide(c)) return raw;
  const stripped = raw.replace(/^\[定时\]\s*/, "").trim();
  return stripped || raw;
}

const isMainActive = computed(
  () => props.activeView === "chat" && Boolean(props.mainConversation && props.currentId === props.mainConversation.id),
);
</script>

<template>
  <aside
    ref="asideRef"
    :role="isMobileDrawer && open ? 'dialog' : undefined"
    :aria-modal="isMobileDrawer && open ? 'true' : undefined"
    :aria-hidden="isMobileDrawer && !open ? 'true' : undefined"
    :inert="isMobileDrawer && !open ? true : undefined"
    :aria-label="isMobileDrawer ? '应用导航侧栏' : '主导航'"
    class="fixed inset-y-0 left-0 z-40 flex h-full shrink-0 touch-pan-y bg-sidebar text-fg will-change-[translate] md:static md:z-20 md:translate-x-0 md:shadow-none"
    :class="[
      open
        ? 'translate-x-0 shadow-2xl transition-[translate] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]'
        : '-translate-x-full transition-[translate] duration-200 ease-in',
    ]"
    :style="drawerStyle"
    @touchstart.passive="onTouchStart"
    @touchmove="onTouchMove"
    @touchend="onTouchEnd"
    @touchcancel="resetSwipe"
    @keydown="onDrawerKeydown"
  >
    <!-- Column 1: Fixed Primary Icon Rail (never expands; Avatar pinned to bottom) -->
    <div
      class="relative z-20 flex w-[60px] shrink-0 flex-col items-center border-r border-line/65 bg-sidebar py-3.5"
    >
      <!-- Web Brand Mark (Desktop title bar owns the brand) -->
      <button
        v-if="!inDesktop"
        type="button"
        class="focus-ring mb-4 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-fg transition-transform duration-150 hover:scale-[1.05] active:scale-[0.97]"
        aria-label="返回主要聊天"
        @mouseenter="showTooltip($event, assistantName, '回到主要聊天')"
        @mouseleave="hideTooltip"
        @click="selectMain"
      >
        <span class="brand-mark-tight icon-m icon-m-lift h-[15px] w-[23px]" aria-hidden="true" />
      </button>

      <!-- Main Navigation Icons: Chat, Search, Library -->
      <nav aria-label="主功能导航" class="flex flex-1 flex-col items-center justify-center gap-2.5">
        <!-- 聊天 -->
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-colors"
          :class="
            activeView === 'chat'
              ? 'bg-hover text-fg shadow-xs dark:bg-active'
              : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
          "
          :aria-current="activeView === 'chat' ? 'page' : undefined"
          aria-label="聊天"
          @mouseenter="showTooltip($event, '聊天', '主聊天与旁聊')"
          @mouseleave="hideTooltip"
          @focus="showTooltip($event, '聊天', '主聊天与旁聊')"
          @blur="hideTooltip"
          @click="onClickChatRail"
        >
          <AppIcon name="chat" :active="activeView === 'chat'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
        </button>

        <!-- 动态 -->
        <button
          type="button"
          class="focus-ring relative flex h-10 w-10 items-center justify-center rounded-full transition-colors"
          :class="
            activeView === 'posts'
              ? 'bg-hover text-fg shadow-xs dark:bg-active'
              : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
          "
          :aria-current="activeView === 'posts' ? 'page' : undefined"
          aria-label="动态"
          @mouseenter="showTooltip($event, '动态', '仅你可见的 AI 与私人动态')"
          @mouseleave="hideTooltip"
          @focus="showTooltip($event, '动态', '仅你可见的 AI 与私人动态')"
          @blur="hideTooltip"
          @click="onClickPostsRail"
        >
          <AppIcon name="compass" :active="activeView === 'posts'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
          <span
            v-if="postsStore.hasUnread && activeView !== 'posts'"
            class="absolute right-2 top-2 h-2 w-2 rounded-full bg-danger ring-2 ring-sidebar"
            aria-hidden="true"
          />
        </button>

        <!-- 搜索 -->
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover/70 hover:text-fg"
          aria-label="搜索"
          @mouseenter="showTooltip($event, '搜索', '搜索标题与正文 (Ctrl+K)')"
          @mouseleave="hideTooltip"
          @focus="showTooltip($event, '搜索', '搜索标题与正文 (Ctrl+K)')"
          @blur="hideTooltip"
          @click="onClickSearchRail"
        >
          <AppIcon name="search" class="h-[20px] w-[20px]" :stroke-width="1.9" />
        </button>

        <!-- 资料库 -->
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-colors"
          :class="
            activeView === 'library'
              ? 'bg-hover text-fg shadow-xs dark:bg-active'
              : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
          "
          :aria-current="activeView === 'library' ? 'page' : undefined"
          aria-label="资料库"
          @mouseenter="showTooltip($event, '资料库', '统一管理所有聊天文件')"
          @mouseleave="hideTooltip"
          @focus="showTooltip($event, '资料库', '统一管理所有聊天文件')"
          @blur="hideTooltip"
          @click="onClickLibraryRail"
        >
          <AppIcon name="folder" :active="activeView === 'library'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
        </button>

        <!-- 定时任务 -->
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-colors"
          :class="
            activeView === 'schedules'
              ? 'bg-hover text-fg shadow-xs dark:bg-active'
              : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
          "
          :aria-current="activeView === 'schedules' ? 'page' : undefined"
          aria-label="定时任务"
          @mouseenter="showTooltip($event, '定时任务', '自动化定时指令与运行历史')"
          @mouseleave="hideTooltip"
          @focus="showTooltip($event, '定时任务', '自动化定时指令与运行历史')"
          @blur="hideTooltip"
          @click="onClickSchedulesRail"
        >
          <AppIcon name="clock" :active="activeView === 'schedules'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
        </button>
      </nav>

      <!-- Bottom Pinned User Avatar (Opens Quick Settings Card) -->
      <div class="mt-auto pt-3">
        <button
          ref="avatarBtnRef"
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-transform duration-150 hover:scale-[1.04]"
          aria-label="账号与快捷设置"
          :aria-expanded="quickCardOpen"
          @mouseenter="showTooltip($event, auth.user?.display_name || '账号与设置', credits.tierLabel)"
          @mouseleave="hideTooltip"
          @click.stop="toggleQuickCard"
        >
          <img
            v-if="auth.user?.avatar_url && !avatarLoadFailed"
            :src="auth.user.avatar_url"
            alt=""
            class="h-9 w-9 rounded-full bg-surface object-cover ring-1 ring-line"
            @error="avatarLoadFailed = true"
          />
          <span
            v-else
            class="flex h-9 w-9 items-center justify-center rounded-full bg-surface text-[13px] font-semibold text-fg ring-1 ring-line transition-colors hover:bg-hover"
          >
            {{ initials }}
          </span>
        </button>
      </div>
    </div>

    <!-- Column 2: Collapsible Secondary Sidebar (Search + Main Chat + Side Chats) -->
    <div
      class="relative flex h-full flex-col overflow-hidden bg-sidebar transition-[width,opacity] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]"
      :class="
        isSecondaryCollapsed
          ? 'pointer-events-none w-0 opacity-0'
          : 'w-[252px] opacity-100'
      "
      :aria-hidden="isSecondaryCollapsed ? 'true' : undefined"
      :inert="isSecondaryCollapsed ? true : undefined"
    >
      <div class="flex h-full w-[252px] flex-col">
        <!-- Top Search Pill & Collapse / Mobile Close -->
        <div class="flex shrink-0 items-center gap-2 px-3 pb-2.5 pt-3.5">
          <button
            type="button"
            class="focus-ring flex h-9.5 min-w-0 flex-1 items-center gap-2 rounded-full border border-line/80 bg-canvas/85 px-3 text-left text-[13.5px] text-fg-faint transition-colors hover:border-line-strong hover:text-fg-muted dark:bg-surface/80"
            @click="onClickSearchRail"
          >
            <AppIcon name="search" class="h-4 w-4 shrink-0" :stroke-width="1.95" />
            <span class="truncate">搜索</span>
          </button>

          <!-- Desktop collapse button -->
          <button
            type="button"
            class="focus-ring hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-faint transition-colors hover:bg-hover hover:text-fg md:flex"
            aria-label="收起侧栏"
            title="收起侧栏 (Ctrl+B)"
            @click="emit('toggle-collapse')"
          >
            <AppIcon name="panel-left" class="h-4.5 w-4.5" :stroke-width="1.85" />
          </button>

          <!-- Mobile close drawer button -->
          <button
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-faint transition-colors hover:bg-hover hover:text-fg md:hidden"
            aria-label="关闭侧栏"
            @click="emit('close')"
          >
            <AppIcon name="close" class="h-4.5 w-4.5" :stroke-width="2" />
          </button>
        </div>

        <!-- Pinned Main Chat Entry (Assistant Avatar + Custom Nickname + 主聊 tag) -->
        <div class="shrink-0 px-3 pb-2">
          <button
            type="button"
            class="focus-ring flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors"
            :class="
              isMainActive
                ? 'bg-hover/95 text-fg dark:bg-active'
                : 'text-fg/90 hover:bg-hover/65 hover:text-fg'
            "
            @click="selectMain"
          >
            <span class="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-canvas ring-1 ring-line/80 dark:bg-surface">
              <img
                v-if="assistantAvatarUrl && !assistantAvatarFailed"
                :src="assistantAvatarUrl"
                :alt="assistantName"
                class="h-full w-full object-cover"
                @error="assistantAvatarFailed = true"
              />
              <span v-else class="brand-mark-tight h-[10px] w-[15px] text-fg" aria-hidden="true" />
            </span>

            <span class="min-w-0 flex-1 truncate text-[14px] font-medium">
              {{ assistantName }}
            </span>

            <span
              v-if="isRunning(mainConversation)"
              class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
              aria-label="运行中"
            />

            <span class="shrink-0 rounded-full bg-surface px-1.5 py-0.5 text-[10.5px] font-medium leading-none text-fg-muted dark:bg-canvas/70">
              主聊
            </span>
          </button>
        </div>

        <!-- Side Chats Section Header + New Side Chat Button -->
        <div class="flex shrink-0 items-center justify-between px-4 pb-1 pt-2">
          <span class="text-[12.5px] font-medium text-fg-faint">旁聊</span>
          <button
            type="button"
            class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            aria-label="新建旁聊"
            title="新建旁聊"
            @click="createSide"
          >
            <AppIcon name="plus" class="h-4 w-4" :stroke-width="2.1" />
          </button>
        </div>

        <!-- Side Chats List -->
        <nav v-scrollbar class="custom-scrollbar flex-1 overflow-y-auto pl-3 pr-1 pb-4">
          <div v-if="loading && !sideConversations.length && !mainConversation" class="space-y-2 px-1 py-2">
            <div v-for="i in 4" :key="i" class="h-9.5 w-full animate-pulse rounded-xl bg-surface" />
          </div>

          <template v-else>
            <div v-if="sideSections.length" class="pt-0.5">
              <div v-for="(section, sIdx) in sideSections" :key="section.key" :class="sIdx > 0 ? 'mt-3' : ''">
                <p v-if="section.label" class="px-2.5 pb-1 text-[11px] font-medium text-fg-faint">
                  {{ section.label }}
                </p>
                <div class="space-y-0.5">
                  <div
                    v-for="c in section.items"
                    :key="c.id"
                    class="group/item relative flex items-center rounded-xl pr-1 transition-colors duration-150"
                    :class="
                      activeView === 'chat' && c.id === currentId
                        ? 'bg-hover/90 dark:bg-active'
                        : 'hover:bg-hover/65'
                    "
                  >
                    <button
                      type="button"
                      class="focus-ring flex h-9.5 min-w-0 flex-1 items-center gap-2 rounded-xl pl-2.5 pr-1 text-left text-[13.5px] transition-colors"
                      :class="
                        activeView === 'chat' && c.id === currentId
                          ? 'font-medium text-fg'
                          : 'text-fg-muted hover:text-fg'
                      "
                      @click="selectSide(c.id)"
                    >
                      <span
                        v-if="isRunning(c)"
                        class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                      />
                      <AppIcon
                        v-if="c.is_pinned"
                        name="pin"
                        motion="none"
                        class="h-3.5 w-3.5 shrink-0 text-fg-faint"
                        :stroke-width="1.9"
                        aria-label="已置顶"
                      />
                      <span class="min-w-0 flex-1 truncate">{{ displaySideTitle(c) }}</span>
                      <span
                        v-if="isScheduledSide(c)"
                        class="inline-flex shrink-0 items-center gap-0.5 rounded-full bg-surface px-1.5 py-0.5 text-[10.5px] font-medium leading-none text-fg-muted dark:bg-canvas/70"
                        title="定时任务旁聊"
                      >
                        <AppIcon name="clock" motion="none" class="h-2.5 w-2.5 shrink-0" :stroke-width="2.1" />
                        <span>定时</span>
                      </span>
                    </button>

                    <button
                      type="button"
                      class="focus-ring flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-fg-faint transition-opacity hover:bg-surface hover:text-fg md:opacity-0 md:group-hover/item:opacity-100"
                      :class="openMenuId === c.id ? 'bg-surface text-fg md:opacity-100' : ''"
                      aria-label="更多操作"
                      @click.stop="toggleMenu(c)"
                    >
                      <AppIcon name="more-horizontal" class="h-4 w-4" />
                    </button>

                    <div
                      v-if="openMenuId === c.id"
                      class="animate-rise absolute right-1 top-10 z-30 w-36 origin-top-right rounded-xl bg-canvas p-1 shadow-lg dark:bg-[#161615]"
                      style="box-shadow: var(--shadow)"
                      @click.stop
                    >
                      <button
                        type="button"
                        class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                        @click="togglePin(c)"
                      >
                        <AppIcon name="pin" class="h-4 w-4 shrink-0" :stroke-width="1.8" />
                        {{ c.is_pinned ? "取消置顶" : "置顶" }}
                      </button>
                      <button
                        type="button"
                        class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                        @click="openRename(c)"
                      >
                        <AppIcon name="edit" class="h-4 w-4 shrink-0" :stroke-width="1.8" />
                        重命名
                      </button>
                      <button
                        type="button"
                        class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-danger transition-colors hover:bg-danger-weak"
                        @click="askDelete(c)"
                      >
                        <AppIcon name="trash" class="h-4 w-4 shrink-0" :stroke-width="1.8" />
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <p
              v-if="!loading && !sideConversations.length"
              class="px-3 py-8 text-center text-[12.5px] leading-relaxed text-fg-faint"
            >
              还没有旁聊<br />点击上方「+」新建旁聊
            </p>
          </template>
        </nav>
      </div>
    </div>

    <!-- Teleported Avatar Quick Settings Card (Account + Quota + Theme + Real Settings Button) -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="opacity-0 translate-y-1 scale-95"
        enter-to-class="opacity-100 translate-y-0 scale-100"
        leave-active-class="transition duration-100 ease-in"
        leave-from-class="opacity-100 translate-y-0 scale-100"
        leave-to-class="opacity-0 translate-y-1 scale-95"
      >
        <div
          v-if="quickCardOpen"
          class="fixed z-50 w-[288px] rounded-2xl bg-canvas p-4 shadow-lg dark:bg-[#161615]"
          :style="{ ...quickCardStyle, boxShadow: 'var(--shadow)' }"
          @click.stop
        >
          <!-- Account summary -->
          <div class="min-w-0">
            <div class="flex items-center gap-1.5">
              <span class="truncate text-[14.5px] font-medium text-fg">
                {{ auth.user?.display_name || auth.user?.email }}
              </span>
              <span
                class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-none"
                :class="tierBadgeClass"
              >
                {{ credits.tierLabel }}
              </span>
            </div>
            <p v-if="auth.user?.email" class="mt-0.5 truncate text-[12.5px] text-fg-faint">{{ auth.user.email }}</p>
          </div>

          <!-- Quota / Usage -->
          <div class="mt-3.5 rounded-xl bg-sidebar/80 p-3 dark:bg-[#0e0e0e]/85">
            <div class="mb-2 flex items-center justify-between">
              <span class="text-[12.5px] font-medium text-fg-muted">额度用量</span>
              <span v-if="credits.overdrawn" class="text-[12px] font-medium text-danger">已用完</span>
            </div>

            <div v-if="credits.loading && !credits.status" class="py-1.5 text-[12.5px] text-fg-faint">
              加载中…
            </div>

            <div v-else-if="credits.status" class="space-y-2.5">
              <div>
                <div class="flex items-center justify-between text-[12.5px] text-fg-muted">
                  <span>本周剩余</span>
                  <span class="font-medium tabular-nums text-fg">
                    {{ credits.status.weekly.limit ? `${credits.weeklyPercent}%` : "不限" }}
                  </span>
                </div>
                <div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface">
                  <div
                    v-if="credits.status.weekly.limit"
                    class="h-full rounded-full transition-[width] duration-500"
                    :class="quotaTone(credits.weeklyPercent)"
                    :style="{ width: `${credits.weeklyPercent}%` }"
                  />
                  <div v-else class="h-full w-full rounded-full bg-fg/65" />
                </div>
                <p v-if="credits.status.weekly.limit" class="mt-1 text-[11.5px] text-fg-faint">
                  {{ fmtReset(credits.status.weekly.reset_at) }} 重置
                </p>
              </div>

              <div v-if="credits.tier !== 'pro'">
                <div class="flex items-center justify-between text-[12.5px] text-fg-muted">
                  <span>5 小时剩余</span>
                  <span class="font-medium tabular-nums text-fg">{{ credits.fiveHourPercent }}%</span>
                </div>
                <div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface">
                  <div
                    class="h-full rounded-full transition-[width] duration-500"
                    :class="quotaTone(credits.fiveHourPercent)"
                    :style="{ width: `${credits.fiveHourPercent}%` }"
                  />
                </div>
                <p class="mt-1 text-[11.5px] text-fg-faint">
                  {{ fmtReset(credits.status.five_hour.reset_at) }} 重置
                </p>
              </div>
            </div>

            <p v-else class="py-1 text-[12.5px] text-fg-faint">暂无额度信息</p>
          </div>

          <!-- Horizontal 3-way theme switcher -->
          <div class="mt-3.5">
            <p class="mb-1.5 text-[12.5px] font-medium text-fg-muted">外观主题</p>
            <div class="grid grid-cols-3 gap-1 rounded-xl bg-surface p-1 dark:bg-[#0e0e0e]">
              <button
                v-for="opt in themeOptions"
                :key="opt.value"
                type="button"
                class="focus-ring flex h-8 items-center justify-center gap-1 whitespace-nowrap rounded-lg px-1.5 text-[12.5px] transition-all"
                :class="
                  preference === opt.value
                    ? 'bg-canvas font-medium text-fg shadow-xs dark:bg-[#242422]'
                    : 'text-fg-muted hover:text-fg'
                "
                @click="setTheme(opt.value, 'bottom-left')"
              >
                <AppIcon
                  v-if="opt.value === 'system'"
                  name="monitor"
                  :active="preference === opt.value"
                  class="h-3.5 w-3.5 shrink-0"
                  :stroke-width="1.85"
                />
                <AppIcon
                  v-else-if="opt.value === 'light'"
                  name="sun"
                  :active="preference === opt.value"
                  class="h-3.5 w-3.5 shrink-0"
                  :stroke-width="1.85"
                />
                <AppIcon
                  v-else
                  name="moon"
                  :active="preference === opt.value"
                  class="h-3.5 w-3.5 shrink-0"
                  :stroke-width="1.85"
                />
                <span>{{ opt.label }}</span>
              </button>
            </div>
          </div>

          <!-- Real Settings Button -->
          <button
            type="button"
            class="focus-ring mt-3.5 flex w-full items-center justify-between rounded-xl border border-line/80 bg-sidebar/60 px-3 py-2.5 text-[13px] font-medium text-fg transition-colors hover:bg-hover dark:bg-[#0e0e0e]/70"
            @click="goToSettings"
          >
            <span class="flex items-center gap-2">
              <AppIcon name="settings" class="h-4 w-4 text-fg-muted" :stroke-width="1.85" />
              <span>设置</span>
            </span>
            <AppIcon name="chevron-right" class="h-4 w-4 text-fg-faint" :stroke-width="2" />
          </button>
        </div>
      </Transition>
    </Teleport>

    <!-- Teleported Floating Tooltip for Primary Icon Rail -->
    <Teleport to="body">
      <div
        v-if="tooltip && isDesktop && !quickCardOpen"
        role="tooltip"
        class="pointer-events-none fixed z-50 -translate-y-1/2 rounded-xl bg-canvas px-3 py-1.5 shadow-lg dark:bg-[#161615]"
        :style="{ top: `${tooltip.top}px`, left: `${tooltip.left}px`, boxShadow: 'var(--shadow)' }"
      >
        <p class="max-w-[220px] truncate text-[13px] font-medium text-fg">{{ tooltip.title }}</p>
        <p v-if="tooltip.sub" class="mt-0.5 text-[11.5px] text-fg-faint">{{ tooltip.sub }}</p>
      </div>
    </Teleport>

    <!-- Rename Side Chat Modal -->
    <BaseModal :open="!!renameTarget" title="重命名旁聊" @close="closeRename">
      <BaseInput
        v-model="renameText"
        label="标题"
        rounded="full"
        soft
        :disabled="renameGenerating"
        :error="renameError"
        :placeholder="renameGenerating ? '正在生成标题…' : ''"
        @keydown.enter="confirmRename"
      >
        <template #suffix>
          <button
            type="button"
            class="focus-ring flex h-8.5 w-8.5 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
            :class="renameGenerating ? 'is-generating text-fg' : ''"
            :disabled="renameGenerating"
            :aria-label="renameGenerating ? '正在生成标题' : 'AI 生成标题'"
            :title="renameGenerating ? '正在生成标题…' : 'AI 生成标题'"
            @click="generateRenameTitle"
          >
            <AppIcon name="sparkles" class="h-5 w-5" :stroke-width="1.95" />
          </button>
        </template>
      </BaseInput>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="renameSaving" @click="closeRename">取消</BaseButton>
        <BaseButton rounded="full" :loading="renameSaving" :disabled="renameGenerating || !renameText.trim()" @click="confirmRename">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- Delete Side Chat Modal -->
    <BaseModal :open="!!deleteTarget" title="删除旁聊" @close="closeDelete">
      <div class="space-y-3">
        <p class="text-[14.5px] leading-relaxed text-fg-muted">
          确定删除旁聊「<span class="font-medium text-fg">{{ deleteTarget?.title }}</span>」吗？此操作不可撤销；该旁聊中上传的文件仍会保留在资料库中。
        </p>
        <p v-if="deleteError" role="alert" class="text-[12.5px] text-danger">{{ deleteError }}</p>
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="deleteSaving" @click="closeDelete">取消</BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="deleteSaving" @click="confirmDelete">删除</BaseButton>
      </template>
    </BaseModal>
  </aside>
</template>
