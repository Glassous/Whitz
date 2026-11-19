<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "@web/stores/auth";
import { useCreditsStore } from "@web/stores/credits";
import { useTheme, type ThemePreference } from "@web/lib/theme";
import { useDesktopStore } from "../../stores/desktop";
import { useRuntimeStore } from "../../stores/runtime";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  mode: "chat" | "work";
  open?: boolean;
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  "drag-progress": [number | null];
}>();

const router = useRouter();
const auth = useAuthStore();
const credits = useCreditsStore();
const desktop = useDesktopStore();
const runtime = useRuntimeStore();
const { preference, set: setTheme } = useTheme();

const themeOptions: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

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
  if (shouldClose) emit("close");
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

// Quick card popover
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
    if (desktop.loggedIn) void credits.fetch().catch(() => undefined);
  }
}

watch(isRail, () => {
  quickCardOpen.value = false;
});

// Floating tooltip for collapsed rail
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

const avatarLoadFailed = ref(false);
watch(
  () => auth.user?.avatar_url ?? desktop.user?.avatar_url,
  () => {
    avatarLoadFailed.value = false;
  },
);

const displayUser = computed(() => auth.user ?? desktop.user);
const isBuiltinModel = computed(() => {
  const m = runtime.settings?.model;
  if (!m) return false;
  return m.mode === "builtin" || m.active_model_label.startsWith("whitz/");
});

const initials = computed(() => {
  if (!desktop.loggedIn) return "L";
  const name = displayUser.value?.display_name?.trim();
  if (name) return Array.from(name)[0]?.toUpperCase() ?? "U";
  return displayUser.value?.email?.slice(0, 1).toUpperCase() ?? "U";
});

const settingsRoute = computed(() => (props.mode === "work" ? { name: "work-settings" } : { name: "settings" }));
const settingsTitle = computed(() => (props.mode === "work" ? "Work 本地设置" : "Chat 设置"));

function openSettings() {
  quickCardOpen.value = false;
  hideTooltip();
  emit("close");
  void router.push(settingsRoute.value);
}

function goLogin() {
  quickCardOpen.value = false;
  hideTooltip();
  emit("close");
  void router.push({ name: "login", query: { redirect: props.mode === "work" ? "/work" : "/chat" } });
}

function closePopovers() {
  quickCardOpen.value = false;
}

onMounted(() => {
  document.addEventListener("click", closePopovers);
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  if (desktop.loggedIn) void credits.fetch().catch(() => undefined);
});

onBeforeUnmount(() => {
  document.removeEventListener("click", closePopovers);
  mediaQuery?.removeEventListener("change", onMediaChange);
});

defineExpose({ showTooltip, hideTooltip, isRail });
</script>

<template>
  <aside
    ref="asideRef"
    :role="isMobileDrawer && open ? 'dialog' : undefined"
    :aria-modal="isMobileDrawer && open ? 'true' : undefined"
    :aria-hidden="isMobileDrawer && !open ? 'true' : undefined"
    :inert="isMobileDrawer && !open ? true : undefined"
    :aria-label="isMobileDrawer ? '导航侧栏' : undefined"
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
    <!-- Subtle atmospheric top aura (matches ConversationSidebar) -->
    <div class="pointer-events-none absolute inset-x-0 top-0 h-44 overflow-hidden">
      <div
        class="h-full w-full opacity-55 dark:opacity-35"
        style="background: radial-gradient(120% 85% at 25% 0%, var(--hover) 0%, transparent 72%)"
      />
    </div>

    <!-- Mobile drawer header -->
    <div class="relative z-10 flex shrink-0 items-center justify-between px-3.5 pb-2 pt-3.5 md:hidden">
      <div class="flex min-w-0 items-center">
        <span class="flex h-10 w-10 shrink-0 items-center justify-center">
          <span class="brand-mark-tight h-[16px] w-[24px]" aria-hidden="true" />
        </span>
        <span
          class="-ml-[7px] translate-y-[0.5px] select-none whitespace-nowrap text-[22px] font-semibold leading-none tracking-tight text-fg"
        >
          hitz
        </span>
      </div>
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

    <!-- Top context (e.g. Workspace folder switcher in Work mode) -->
    <div v-if="$slots['top-context']" class="relative z-20 mt-4 shrink-0 px-3.5 pb-1">
      <slot name="top-context" :is-rail="isRail" :show-tooltip="showTooltip" :hide-tooltip="hideTooltip" />
    </div>

    <!-- Action zone -->
    <div
      class="relative z-10 shrink-0 space-y-2 px-3.5 pb-2"
      :class="$slots['top-context'] ? 'mt-1.5' : 'mt-5'"
    >
      <slot name="actions" :is-rail="isRail" :show-tooltip="showTooltip" :hide-tooltip="hideTooltip" />
    </div>

    <!-- Conversation list (hidden when collapsed) -->
    <nav v-scrollbar class="custom-scrollbar relative z-10 flex-1 overflow-y-auto pl-3 pr-1 pb-3">
      <template v-if="!isRail">
        <slot name="list" />
      </template>
    </nav>

    <!-- Bottom Profile & Mode-Independent Settings -->
    <div class="relative z-20 shrink-0 px-3.5 py-3">
      <div class="flex items-center gap-1.5">
        <button
          ref="avatarBtnRef"
          type="button"
          class="focus-ring flex min-w-0 items-center gap-2 rounded-xl text-left transition-colors"
          :class="isRail ? 'w-10' : 'flex-1 pr-2 hover:bg-hover/65'"
          aria-label="个人与额度面板"
          @mouseenter="
            showTooltip(
              $event,
              desktop.loggedIn ? displayUser?.display_name || '个人快捷面板' : '本地工作模式',
              desktop.loggedIn ? credits.tierLabel : '未登录 · 仅可使用自带 Key',
            )
          "
          @mouseleave="hideTooltip"
          @click.stop="toggleQuickCard"
        >
          <span class="flex h-10 w-10 shrink-0 items-center justify-center">
            <img
              v-if="desktop.loggedIn && displayUser?.avatar_url && !avatarLoadFailed"
              :src="displayUser.avatar_url"
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
              {{ desktop.loggedIn ? displayUser?.display_name || displayUser?.email : "本地模式" }}
            </span>
            <span
              v-if="desktop.loggedIn"
              class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-none"
              :class="tierBadgeClass"
            >
              {{ credits.tierLabel }}
            </span>
            <span
              v-else
              class="shrink-0 rounded-full bg-surface px-2 py-0.5 text-[10.5px] font-medium leading-none text-fg-faint"
            >
              未登录
            </span>
          </span>
        </button>

        <button
          v-if="!isRail"
          type="button"
          class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/70 hover:text-fg"
          :aria-label="settingsTitle"
          :title="settingsTitle"
          @click="openSettings"
        >
          <svg class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85">
            <circle cx="12" cy="12" r="3" />
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"
            />
          </svg>
        </button>
      </div>
    </div>

    <!-- Teleported Quick Card -->
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
          class="fixed z-50 w-[292px] rounded-2xl bg-canvas p-4 shadow-lg dark:bg-[#161615]"
          :style="{ ...quickCardStyle, boxShadow: 'var(--shadow)' }"
          @click.stop
        >
          <template v-if="desktop.loggedIn">
            <div class="min-w-0">
              <div class="flex items-center gap-1.5">
                <span class="truncate text-[14.5px] font-medium text-fg">
                  {{ displayUser?.display_name || displayUser?.email }}
                </span>
                <span
                  class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-none"
                  :class="tierBadgeClass"
                >
                  {{ credits.tierLabel }}
                </span>
              </div>
              <p v-if="displayUser?.email" class="mt-0.5 truncate text-[12.5px] text-fg-faint">{{ displayUser.email }}</p>
            </div>

            <div class="mt-3.5 rounded-xl bg-sidebar/80 p-3 dark:bg-[#0e0e0e]/85">
              <div class="mb-2 flex items-center justify-between">
                <span class="text-[12.5px] font-medium text-fg-muted">账号额度</span>
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

              <p v-if="mode === 'work'" class="mt-2.5 border-t border-line/60 pt-2 text-[11px] leading-relaxed text-fg-faint">
                {{
                  isBuiltinModel
                    ? "当前使用「Whitz 内置」模型，与 Chat 共享账号额度。"
                    : "当前使用自带 Key（BYOK），不消耗 Whitz 账号额度。"
                }}
              </p>
            </div>
          </template>

          <template v-else>
            <div class="min-w-0">
              <p class="text-[14.5px] font-medium text-fg">本地工作模式</p>
              <p class="mt-1 text-[12px] leading-relaxed text-fg-muted">
                当前未登录 Whitz 账号，可通过自带 API Key 使用完整本地工作台；登录后可使用「Whitz 内置」共享额度。
              </p>
              <BaseButton size="sm" class="mt-3 w-full" @click="goLogin">登录 Whitz 账号</BaseButton>
            </div>
          </template>

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
                <span>{{ opt.label }}</span>
              </button>
            </div>
          </div>

          <button
            type="button"
            class="focus-ring mt-3 flex w-full items-center justify-between rounded-xl border border-line px-3 py-2 text-[12.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            @click="openSettings"
          >
            <span>{{ settingsTitle }}</span>
            <span class="text-fg-faint">→</span>
          </button>
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
        <p class="max-w-[240px] truncate text-[13.5px] font-medium text-fg">{{ tooltip.title }}</p>
        <p v-if="tooltip.sub" class="mt-0.5 max-w-[240px] truncate text-[12px] text-fg-faint">{{ tooltip.sub }}</p>
      </div>
    </Teleport>
  </aside>
</template>
