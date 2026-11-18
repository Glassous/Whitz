<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { streamSSE } from "../../api/sse";
import type { Conversation } from "../../types";
import { useAuthStore } from "../../stores/auth";
import { useCreditsStore } from "../../stores/credits";
import { useTheme, type ThemePreference } from "../../lib/theme";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import BaseInput from "../ui/BaseInput.vue";

const props = defineProps<{
  conversations: Conversation[];
  currentId: string | null;
  loading?: boolean;
  open?: boolean;
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  select: [string];
  create: [];
  rename: [string, string];
  delete: [string];
  close: [];
  "open-search": [];
  "drag-progress": [number | null];
}>();

const auth = useAuthStore();
const credits = useCreditsStore();
const { preference, set: setTheme } = useTheme();

const themeOptions: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

// Track desktop breakpoint so mobile drawer always renders full expanded layout.
const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;
function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
  if (!e.matches) hideTooltip();
}

const isRail = computed(() => Boolean(props.collapsed && isDesktop.value));
const isMobileDrawer = computed(() => !isDesktop.value);

// 1:1 finger-following left-swipe to close on mobile
const asideRef = ref<HTMLElement | null>(null);
const isSwiping = ref(false);
const dragOffsetX = ref(0);
let swipeStartX = 0;
let swipeStartY = 0;
let swipeStartTime = 0;
let swipeLocked: "horizontal" | "vertical" | null = null;
let drawerWidth = 276;

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
  drawerWidth = asideRef.value?.offsetWidth || 276;
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

// Quick card popover (opened by clicking avatar)
const quickCardOpen = ref(false);
const avatarBtnRef = ref<HTMLElement | null>(null);
const quickCardStyle = ref<{ left: string; bottom: string }>({ left: "16px", bottom: "60px" });

function updateQuickCardPosition() {
  const rect = avatarBtnRef.value?.getBoundingClientRect();
  if (!rect) return;
  if (isRail.value) {
    quickCardStyle.value = {
      left: `${rect.right + 12}px`,
      bottom: `${Math.max(12, window.innerHeight - rect.bottom)}px`,
    };
  } else {
    quickCardStyle.value = {
      left: `${rect.left}px`,
      bottom: `${window.innerHeight - rect.top + 8}px`,
    };
  }
}

function toggleQuickCard() {
  quickCardOpen.value = !quickCardOpen.value;
  if (quickCardOpen.value) {
    hideTooltip();
    updateQuickCardPosition();
    void credits.fetch();
  }
}

watch(isRail, () => {
  quickCardOpen.value = false;
});

// Floating tooltip for collapsed rail (teleported to body to avoid overflow clipping)
const tooltip = ref<{ title: string; sub?: string; top: number; left: number } | null>(null);

function showTooltip(event: MouseEvent | FocusEvent, title: string, sub?: string) {
  if (!isRail.value) return;
  const target = event.currentTarget as HTMLElement | null;
  if (!target) return;
  const rect = target.getBoundingClientRect();
  tooltip.value = {
    title,
    sub,
    top: rect.top + rect.height / 2,
    left: rect.right + 12,
  };
}

function hideTooltip() {
  tooltip.value = null;
}

function openSearch() {
  hideTooltip();
  quickCardOpen.value = false;
  emit("open-search");
  emit("close");
}

const tierBadgeClass = computed(() => {
  if (credits.tier === "pro") {
    return "bg-primary text-primary-fg";
  }
  if (credits.tier === "plus") {
    return "bg-active text-fg";
  }
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

function timestamp(c: Conversation): number {
  return new Date(c.last_message_at ?? c.updated_at ?? c.created_at).getTime();
}

const sortedConversations = computed(() => {
  return props.conversations.toSorted((a, b) => timestamp(b) - timestamp(a));
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

function select(id: string) {
  openMenuId.value = null;
  quickCardOpen.value = false;
  hideTooltip();
  emit("select", id);
  emit("close");
}

function create() {
  openMenuId.value = null;
  quickCardOpen.value = false;
  hideTooltip();
  emit("create");
  emit("close");
}

function toggleMenu(c: Conversation) {
  openMenuId.value = openMenuId.value === c.id ? null : c.id;
}

function closePopovers() {
  openMenuId.value = null;
  quickCardOpen.value = false;
}

onMounted(() => {
  document.addEventListener("click", closePopovers);
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  void credits.fetch();
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closePopovers);
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

function isRunning(c: Conversation): boolean {
  return c.active_run_status === "running" || c.active_run_status === "waiting";
}
</script>

<template>
  <aside
    ref="asideRef"
    :role="isMobileDrawer && open ? 'dialog' : undefined"
    :aria-modal="isMobileDrawer && open ? 'true' : undefined"
    :aria-hidden="isMobileDrawer && !open ? 'true' : undefined"
    :inert="isMobileDrawer && !open ? true : undefined"
    :aria-label="isMobileDrawer ? '对话导航侧栏' : undefined"
    class="group/sidebar fixed inset-y-0 left-0 z-40 flex w-[276px] shrink-0 touch-pan-y flex-col overflow-x-hidden bg-sidebar text-fg will-change-[translate] md:static md:z-20 md:translate-x-0 md:shadow-none"
    :class="[
      open
        ? 'translate-x-0 shadow-2xl transition-[width,translate] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)]'
        : '-translate-x-full transition-[width,translate] duration-200 ease-in',
      isRail ? 'md:w-[68px]' : 'md:w-[276px]',
    ]"
    :style="drawerStyle"
    @touchstart.passive="onTouchStart"
    @touchmove="onTouchMove"
    @touchend="onTouchEnd"
    @touchcancel="resetSwipe"
    @keydown="onDrawerKeydown"
  >
    <!-- Subtle atmospheric top aura -->
    <div class="pointer-events-none absolute inset-x-0 top-0 h-44 overflow-hidden">
      <div
        class="h-full w-full opacity-55 dark:opacity-35"
        style="
          background: radial-gradient(120% 85% at 25% 0%, var(--hover) 0%, transparent 72%);
        "
      />
    </div>

    <!-- Brand header (fixed left padding so W never shifts) -->
    <div class="relative z-10 flex shrink-0 items-center justify-between px-3.5 pb-2 pt-3.5">
      <div class="flex min-w-0 items-center">
        <button
          type="button"
          class="focus-ring relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-fg transition-transform duration-200 hover:scale-[1.04] active:scale-[0.97]"
          title="Whitz"
          aria-label="Whitz 新建对话"
          @click="create"
        >
          <span class="brand-mark-tight h-[16px] w-[24px]" aria-hidden="true" />
        </button>

        <span
          class="-ml-[7px] translate-y-[0.5px] select-none whitespace-nowrap text-[22px] font-semibold leading-none tracking-tight text-fg transition-opacity duration-200"
          :class="isRail ? 'pointer-events-none opacity-0' : 'opacity-100'"
        >
          hitz
        </span>
      </div>

      <!-- Mobile close drawer button -->
      <button
        type="button"
        class="focus-ring rounded-xl p-1.5 text-fg-faint transition-colors hover:bg-hover hover:text-fg md:hidden"
        aria-label="关闭侧栏"
        @click="emit('close')"
      >
        <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>

    <!-- Action zone: New Chat + Search (fixed px-3.5 and w-10 icon slots so icons stay 100% stationary) -->
    <div class="relative z-10 mt-5 shrink-0 space-y-2.5 px-3.5 pb-2">
      <!-- New Chat CTA (bigger, bolder icon & text, borderless directly on sidebar) -->
      <button
        type="button"
        class="focus-ring group/new flex h-10.5 w-full items-center overflow-hidden rounded-xl text-[14.5px] font-semibold text-fg/90 transition-colors duration-150 hover:bg-hover/80 hover:text-fg"
        aria-label="新建对话"
        @mouseenter="showTooltip($event, '新建对话', '开启一段新的会话')"
        @mouseleave="hideTooltip"
        @click="create"
      >
        <span class="flex h-10.5 w-10 shrink-0 items-center justify-center">
          <svg
            class="h-[21px] w-[21px] text-fg transition-transform duration-150 group-hover/new:scale-105"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
          >
            <path stroke-linecap="round" d="M12 5v14M5 12h14" />
          </svg>
        </span>
        <span
          class="whitespace-nowrap pr-2.5 text-left transition-opacity duration-200"
          :class="isRail ? 'pointer-events-none opacity-0' : 'opacity-100'"
        >
          新建对话
        </span>
      </button>

      <!-- Search CTA (borderless, no background, opens central search modal) -->
      <button
        type="button"
        class="focus-ring group/search flex h-10.5 w-full items-center overflow-hidden rounded-xl text-[14.5px] font-semibold text-fg/85 transition-colors duration-150 hover:bg-hover/80 hover:text-fg"
        aria-label="搜索对话"
        @mouseenter="showTooltip($event, '搜索对话', '搜索标题与正文 (Ctrl+K)')"
        @mouseleave="hideTooltip"
        @click="openSearch"
      >
        <span class="flex h-10.5 w-10 shrink-0 items-center justify-center">
          <svg
            class="h-5 w-5 text-fg-muted transition-colors group-hover/search:text-fg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.2"
          >
            <circle cx="11" cy="11" r="7" />
            <path stroke-linecap="round" d="M20 20l-3.5-3.5" />
          </svg>
        </span>
        <span
          class="whitespace-nowrap pr-2.5 text-left transition-opacity duration-200"
          :class="isRail ? 'pointer-events-none opacity-0' : 'opacity-100'"
        >
          搜索对话
        </span>
      </button>
    </div>

    <!-- Conversation list (hidden when collapsed) -->
    <nav v-scrollbar class="custom-scrollbar relative z-10 flex-1 overflow-y-auto pl-3 pr-1 pb-3">
      <template v-if="!isRail">
        <!-- Loading skeleton -->
        <div v-if="loading && !conversations.length" class="space-y-2 py-3 px-1">
          <div
            v-for="i in 4"
            :key="i"
            class="h-10 w-full animate-pulse rounded-xl bg-surface"
          />
        </div>

        <!-- Expanded Flat Conversation List (no date grouping) -->
        <template v-else>
          <div v-if="sortedConversations.length" class="space-y-0.5 pt-2">
            <div
              v-for="c in sortedConversations"
              :key="c.id"
              class="group/item relative flex items-center rounded-xl pr-1 transition-colors duration-150"
              :class="c.id === currentId ? 'bg-hover/90 dark:bg-active' : 'hover:bg-hover/65'"
            >
              <button
                type="button"
                class="focus-ring flex h-10 min-w-0 flex-1 items-center gap-2 rounded-xl pl-3 pr-1 text-left text-[14px] transition-colors"
                :class="c.id === currentId ? 'font-medium text-fg' : 'text-fg-muted hover:text-fg'"
                @click="select(c.id)"
              >
                <span
                  v-if="isRunning(c)"
                  class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                />
                <span class="truncate">{{ c.title }}</span>
              </button>

              <button
                type="button"
                class="focus-ring flex h-7.5 w-7.5 shrink-0 items-center justify-center rounded-lg text-fg-faint transition-opacity hover:bg-surface hover:text-fg md:opacity-0 md:group-hover/item:opacity-100"
                :class="openMenuId === c.id ? 'md:opacity-100 bg-surface text-fg' : ''"
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
                class="animate-rise absolute right-1 top-10.5 z-30 w-34 origin-top-right rounded-xl bg-canvas p-1 shadow-lg dark:bg-[#161615]"
                style="box-shadow: var(--shadow)"
                @click.stop
              >
                <button
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                  @click="openRename(c)"
                >
                  <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M11 4H4v16h16v-7M18.5 2.5a2.1 2.1 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                  重命名
                </button>
                <button
                  type="button"
                  class="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13.5px] text-danger transition-colors hover:bg-danger-weak"
                  @click="askDelete(c)"
                >
                  <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" />
                  </svg>
                  删除
                </button>
              </div>
            </div>
          </div>

          <p
            v-if="!loading && !conversations.length"
            class="px-2 py-10 text-center text-[13px] leading-relaxed text-fg-faint"
          >
            还没有对话<br />点击上方「新建对话」开始
          </p>
        </template>
      </template>
    </nav>

    <!-- Bottom Profile & Settings (fixed px-3.5 py-3 and w-10 avatar slot so avatar never moves) -->
    <div class="relative z-20 shrink-0 px-3.5 py-3">
      <div class="flex items-center gap-1.5">
        <button
          ref="avatarBtnRef"
          type="button"
          class="focus-ring flex min-w-0 items-center gap-2 rounded-xl text-left transition-colors"
          :class="isRail ? 'w-10' : 'flex-1 pr-2 hover:bg-hover/65'"
          aria-label="个人快捷面板"
          @mouseenter="showTooltip($event, auth.user?.display_name || '个人快捷面板', credits.tierLabel)"
          @mouseleave="hideTooltip"
          @click.stop="toggleQuickCard"
        >
          <span class="flex h-10 w-10 shrink-0 items-center justify-center">
            <img
              v-if="auth.user?.avatar_url && !avatarLoadFailed"
              :src="auth.user.avatar_url"
              alt=""
              class="h-9 w-9 rounded-full bg-surface object-cover"
              @error="avatarLoadFailed = true"
            />
            <span
              v-else
              class="flex h-9 w-9 items-center justify-center rounded-full bg-surface text-[13px] font-semibold text-fg transition-colors hover:bg-hover"
            >
              {{ initials }}
            </span>
          </span>
          <span
            class="min-w-0 flex-1 items-center gap-1.5 whitespace-nowrap transition-opacity duration-200"
            :class="isRail ? 'hidden' : 'flex'"
          >
            <span class="truncate text-[14px] font-medium text-fg">
              {{ auth.user?.display_name || auth.user?.email }}
            </span>
            <span
              class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-none"
              :class="tierBadgeClass"
            >
              {{ credits.tierLabel }}
            </span>
          </span>
        </button>

        <router-link
          v-if="!isRail"
          to="/settings"
          class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/70 hover:text-fg"
          aria-label="设置"
          title="设置"
        >
          <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85">
            <circle cx="12" cy="12" r="3" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" />
          </svg>
        </router-link>
      </div>
    </div>

    <!-- Teleported Avatar Quick Card (Usage + 3-way Theme Switcher + Settings link) -->
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
        </div>
      </Transition>
    </Teleport>

    <!-- Teleported Floating Tooltip for Collapsed Rail -->
    <Teleport to="body">
      <div
        v-if="tooltip && isRail && !quickCardOpen"
        class="pointer-events-none fixed z-50 -translate-y-1/2 rounded-xl bg-canvas px-3 py-1.5 shadow-lg dark:bg-[#161615]"
        :style="{ top: `${tooltip.top}px`, left: `${tooltip.left}px`, boxShadow: 'var(--shadow)' }"
      >
        <p class="max-w-[220px] truncate text-[13.5px] font-medium text-fg">{{ tooltip.title }}</p>
        <p v-if="tooltip.sub" class="mt-0.5 text-[12px] text-fg-faint">{{ tooltip.sub }}</p>
      </div>
    </Teleport>

    <!-- Rename Modal -->
    <BaseModal :open="!!renameTarget" title="重命名对话" @close="closeRename">
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

    <!-- Delete Modal -->
    <BaseModal :open="!!deleteTarget" title="删除对话" @close="deleteTarget = null">
      <p class="text-[15px] leading-relaxed text-fg-muted">
        确定删除「<span class="font-medium text-fg">{{ deleteTarget?.title }}</span>」吗？此操作不可撤销。
      </p>
      <template #footer>
        <BaseButton variant="soft" rounded="full" @click="deleteTarget = null">取消</BaseButton>
        <BaseButton variant="danger" rounded="full" @click="confirmDelete">删除</BaseButton>
      </template>
    </BaseModal>
  </aside>
</template>
