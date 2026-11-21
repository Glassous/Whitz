<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { streamSSE } from "../../api/sse";
import type { Conversation } from "../../types";
import { useAuthStore } from "../../stores/auth";
import { sortConversations } from "../../stores/conversations";
import { useCreditsStore } from "../../stores/credits";
import { useTheme, type ThemePreference } from "../../lib/theme";
import { isDesktopHost } from "../../host";
import { isDesktopShell } from "../../host/chrome";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import BaseInput from "../ui/BaseInput.vue";

const props = defineProps<{
  mainConversation: Conversation | null;
  sideConversations: Conversation[];
  currentId: string | null;
  activeView: "chat" | "library";
  loading?: boolean;
  open?: boolean;
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  select: [string];
  "select-main": [];
  "create-side": [];
  "switch-view": ["chat" | "library"];
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
let titleController: AbortController | null = null;
const deleteTarget = ref<Conversation | null>(null);
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

function confirmRename() {
  if (renameGenerating.value) return;
  if (renameTarget.value && renameText.value.trim()) {
    emit("rename", renameTarget.value.id, renameText.value.trim());
  }
  closeRename();
}

function askDelete(c: Conversation) {
  openMenuId.value = null;
  deleteTarget.value = c;
}

function confirmDelete() {
  if (deleteTarget.value) emit("delete", deleteTarget.value.id);
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
        <span class="brand-mark-tight h-[15px] w-[23px]" aria-hidden="true" />
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
          <svg class="h-[20px] w-[20px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.95">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
            />
          </svg>
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
          <svg class="h-[20px] w-[20px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" />
            <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
          </svg>
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
          <svg class="h-[20px] w-[20px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 19.5A2.5 2.5 0 016.5 17H20" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
            <path stroke-linecap="round" d="M9 7h7M9 11h5" />
          </svg>
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
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="7" />
              <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
            </svg>
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
            <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.95">
              <rect x="3" y="4" width="18" height="16" rx="2.5" />
              <path stroke-linecap="round" d="M9 4v16" />
            </svg>
          </button>

          <!-- Mobile close drawer button -->
          <button
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-faint transition-colors hover:bg-hover hover:text-fg md:hidden"
            aria-label="关闭侧栏"
            @click="emit('close')"
          >
            <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
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
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path stroke-linecap="round" d="M12 5v14M5 12h14" />
            </svg>
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
                      <svg
                        v-if="c.is_pinned"
                        class="h-3.5 w-3.5 shrink-0 text-fg-faint"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        aria-label="已置顶"
                      >
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          d="M12 17v5M9 10.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V16a1 1 0 001 1h12a1 1 0 001-1v-.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V7a1 1 0 011-1 2 2 0 000-4H8a2 2 0 000 4 1 1 0 011 1v3.76z"
                        />
                      </svg>
                      <span class="truncate">{{ c.title }}</span>
                    </button>

                    <button
                      type="button"
                      class="focus-ring flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-fg-faint transition-opacity hover:bg-surface hover:text-fg md:opacity-0 md:group-hover/item:opacity-100"
                      :class="openMenuId === c.id ? 'bg-surface text-fg md:opacity-100' : ''"
                      aria-label="更多操作"
                      @click.stop="toggleMenu(c)"
                    >
                      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                        <circle cx="5" cy="12" r="1.6" />
                        <circle cx="12" cy="12" r="1.6" />
                        <circle cx="19" cy="12" r="1.6" />
                      </svg>
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
                        <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                          <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            d="M12 17v5M9 10.76a2 2 0 01-1.11 1.79l-1.78.9A2 2 0 005 15.24V16a1 1 0 001 1h12a1 1 0 001-1v-.76a2 2 0 00-1.11-1.79l-1.78-.9A2 2 0 0115 10.76V7a1 1 0 011-1 2 2 0 000-4H8a2 2 0 000 4 1 1 0 011 1v3.76z"
                          />
                        </svg>
                        {{ c.is_pinned ? "取消置顶" : "置顶" }}
                      </button>
                      <button
                        type="button"
                        class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                        @click="openRename(c)"
                      >
                        <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M11 4H4v16h16v-7M18.5 2.5a2.1 2.1 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                        </svg>
                        重命名
                      </button>
                      <button
                        type="button"
                        class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-danger transition-colors hover:bg-danger-weak"
                        @click="askDelete(c)"
                      >
                        <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" />
                        </svg>
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
                <svg
                  v-if="opt.value === 'system'"
                  class="h-3.5 w-3.5 shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                >
                  <rect x="3" y="4" width="18" height="12" rx="2" />
                  <path stroke-linecap="round" d="M8 20h8M12 16v4" />
                </svg>
                <svg
                  v-else-if="opt.value === 'light'"
                  class="h-3.5 w-3.5 shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                >
                  <circle cx="12" cy="12" r="4" />
                  <path stroke-linecap="round" d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                </svg>
                <svg
                  v-else
                  class="h-3.5 w-3.5 shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
                </svg>
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
              <svg class="h-4 w-4 text-fg-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
                <circle cx="12" cy="12" r="3" />
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"
                />
              </svg>
              <span>设置</span>
            </span>
            <svg class="h-4 w-4 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
            </svg>
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
            :class="renameGenerating ? 'animate-pulse text-fg' : ''"
            :disabled="renameGenerating"
            :aria-label="renameGenerating ? '正在生成标题' : 'AI 生成标题'"
            :title="renameGenerating ? '正在生成标题…' : 'AI 生成标题'"
            @click="generateRenameTitle"
          >
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.6l-1.7-4.6L6 9.3l4.3-1.7L12 3zM18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z"
              />
            </svg>
          </button>
        </template>
      </BaseInput>
      <template #footer>
        <BaseButton variant="soft" rounded="full" @click="closeRename">取消</BaseButton>
        <BaseButton rounded="full" :disabled="renameGenerating" @click="confirmRename">保存</BaseButton>
      </template>
    </BaseModal>

    <!-- Delete Side Chat Modal -->
    <BaseModal :open="!!deleteTarget" title="删除旁聊" @close="deleteTarget = null">
      <p class="text-[14.5px] leading-relaxed text-fg-muted">
        确定删除旁聊「<span class="font-medium text-fg">{{ deleteTarget?.title }}</span>」吗？此操作不可撤销；该旁聊中上传的文件仍会保留在资料库中。
      </p>
      <template #footer>
        <BaseButton variant="soft" rounded="full" @click="deleteTarget = null">取消</BaseButton>
        <BaseButton variant="danger" rounded="full" @click="confirmDelete">删除</BaseButton>
      </template>
    </BaseModal>
  </aside>
</template>
