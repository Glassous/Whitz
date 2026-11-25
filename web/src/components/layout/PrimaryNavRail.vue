<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../../stores/auth";
import { useCreditsStore } from "../../stores/credits";
import { usePostsStore } from "../../stores/posts";
import { useTheme, type ThemePreference } from "../../lib/theme";
import { isDesktopHost } from "../../host";
import { isDesktopShell } from "../../host/chrome";
import AppIcon from "../ui/AppIcon.vue";

const emit = defineEmits<{
  "open-search": [];
  "click-chat-when-active": [];
  navigate: [];
}>();

const route = useRoute();
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

const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;
function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
  if (!e.matches) hideTooltip();
}

const inDesktop = computed(() => isDesktopShell() || isDesktopHost());
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

const activeSection = computed<"chat" | "posts" | "library" | "schedules">(() => {
  const name = String(route.name || "");
  if (name === "posts" || name === "posts-guide" || route.path.startsWith("/posts")) return "posts";
  if (name === "library" || route.path.startsWith("/library")) return "library";
  if (name === "schedules" || route.path.startsWith("/schedules")) return "schedules";
  return "chat";
});

const avatarLoadFailed = ref(false);
watch(
  () => auth.user?.avatar_url,
  () => {
    avatarLoadFailed.value = false;
  },
);

const initials = computed(() => {
  const n = auth.user?.display_name || auth.user?.email || "U";
  return n.slice(0, 1).toUpperCase();
});

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

function onClickBrand() {
  hideTooltip();
  quickCardOpen.value = false;
  void router.push({ name: "chat" });
  emit("navigate");
}

function onClickChat() {
  hideTooltip();
  quickCardOpen.value = false;
  if (activeSection.value !== "chat") {
    void router.push({ name: "chat" });
    emit("navigate");
  } else {
    emit("click-chat-when-active");
  }
}

function onClickPosts() {
  hideTooltip();
  quickCardOpen.value = false;
  postsStore.markRead();
  void router.push({ name: "posts" });
  emit("navigate");
}

function onClickSearch() {
  hideTooltip();
  quickCardOpen.value = false;
  emit("open-search");
  emit("navigate");
}

function onClickLibrary() {
  hideTooltip();
  quickCardOpen.value = false;
  void router.push({ name: "library" });
  emit("navigate");
}

function onClickSchedules() {
  hideTooltip();
  quickCardOpen.value = false;
  void router.push({ name: "schedules" });
  emit("navigate");
}

function goToSettings() {
  quickCardOpen.value = false;
  hideTooltip();
  void router.push({ name: "settings" });
  emit("navigate");
}

function closePopovers() {
  quickCardOpen.value = false;
}

function onEscapeKey(e: KeyboardEvent) {
  if (e.key === "Escape") {
    quickCardOpen.value = false;
    hideTooltip();
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
});
</script>

<template>
  <div
    class="relative z-20 flex h-full w-[60px] shrink-0 flex-col items-center border-r border-line/65 bg-sidebar py-3.5"
  >
    <!-- Web Brand Mark -->
    <button
      v-if="!inDesktop"
      type="button"
      class="focus-ring mb-4 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-fg transition-transform duration-150 hover:scale-[1.05] active:scale-[0.97]"
      aria-label="返回主要聊天"
      @mouseenter="showTooltip($event, assistantName, '回到主要聊天')"
      @mouseleave="hideTooltip"
      @click="onClickBrand"
    >
      <span class="brand-mark-tight icon-m icon-m-lift h-[15px] w-[23px]" aria-hidden="true" />
    </button>

    <!-- Primary Navigation Icons -->
    <nav aria-label="主功能导航" class="flex flex-1 flex-col items-center justify-center gap-2.5">
      <!-- 聊天 -->
      <button
        type="button"
        class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-colors"
        :class="
          activeSection === 'chat'
            ? 'bg-hover text-fg shadow-xs dark:bg-active'
            : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
        "
        :aria-current="activeSection === 'chat' ? 'page' : undefined"
        aria-label="聊天"
        @mouseenter="showTooltip($event, '聊天', '主聊天与旁聊')"
        @mouseleave="hideTooltip"
        @focus="showTooltip($event, '聊天', '主聊天与旁聊')"
        @blur="hideTooltip"
        @click="onClickChat"
      >
        <AppIcon name="chat" :active="activeSection === 'chat'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
      </button>

      <!-- 动态 -->
      <button
        type="button"
        class="focus-ring relative flex h-10 w-10 items-center justify-center rounded-full transition-colors"
        :class="
          activeSection === 'posts'
            ? 'bg-hover text-fg shadow-xs dark:bg-active'
            : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
        "
        :aria-current="activeSection === 'posts' ? 'page' : undefined"
        aria-label="动态"
        @mouseenter="showTooltip($event, '动态', '仅你可见的私人动态')"
        @mouseleave="hideTooltip"
        @focus="showTooltip($event, '动态', '仅你可见的私人动态')"
        @blur="hideTooltip"
        @click="onClickPosts"
      >
        <AppIcon name="compass" :active="activeSection === 'posts'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
        <span
          v-if="postsStore.hasUnread && activeSection !== 'posts'"
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
        @click="onClickSearch"
      >
        <AppIcon name="search" class="h-[20px] w-[20px]" :stroke-width="1.9" />
      </button>

      <!-- 资料库 -->
      <button
        type="button"
        class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-colors"
        :class="
          activeSection === 'library'
            ? 'bg-hover text-fg shadow-xs dark:bg-active'
            : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
        "
        :aria-current="activeSection === 'library' ? 'page' : undefined"
        aria-label="资料库"
        @mouseenter="showTooltip($event, '资料库', '统一管理所有聊天文件')"
        @mouseleave="hideTooltip"
        @focus="showTooltip($event, '资料库', '统一管理所有聊天文件')"
        @blur="hideTooltip"
        @click="onClickLibrary"
      >
        <AppIcon name="folder" :active="activeSection === 'library'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
      </button>

      <!-- 定时任务 -->
      <button
        type="button"
        class="focus-ring flex h-10 w-10 items-center justify-center rounded-full transition-colors"
        :class="
          activeSection === 'schedules'
            ? 'bg-hover text-fg shadow-xs dark:bg-active'
            : 'text-fg-muted hover:bg-hover/70 hover:text-fg'
        "
        :aria-current="activeSection === 'schedules' ? 'page' : undefined"
        aria-label="定时任务"
        @mouseenter="showTooltip($event, '定时任务', '自动化定时指令与运行历史')"
        @mouseleave="hideTooltip"
        @focus="showTooltip($event, '定时任务', '自动化定时指令与运行历史')"
        @blur="hideTooltip"
        @click="onClickSchedules"
      >
        <AppIcon name="clock" :active="activeSection === 'schedules'" class="h-[20px] w-[20px]" :stroke-width="1.85" />
      </button>
    </nav>

    <!-- Bottom Pinned User Avatar -->
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

    <!-- Teleported Avatar Quick Settings Card -->
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

          <div class="mt-3.5 rounded-xl bg-sidebar/80 p-3 dark:bg-[#0e0e0e]/85">
            <div class="mb-2 flex items-center justify-between">
              <span class="text-[12.5px] font-medium text-fg-muted">额度用量</span>
              <span v-if="credits.overdrawn" class="text-[12px] font-medium text-danger">已用完</span>
            </div>
            <div v-if="credits.loading && !credits.status" class="py-1.5 text-[12.5px] text-fg-faint">加载中…</div>
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
                <p class="mt-1 text-[11.5px] text-fg-faint">{{ fmtReset(credits.status.five_hour.reset_at) }} 重置</p>
              </div>
            </div>
            <p v-else class="py-1 text-[12.5px] text-fg-faint">暂无额度信息</p>
          </div>

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
                />
                <AppIcon
                  v-else-if="opt.value === 'light'"
                  name="sun"
                  :active="preference === opt.value"
                  class="h-3.5 w-3.5 shrink-0"
                />
                <AppIcon v-else name="moon" :active="preference === opt.value" class="h-3.5 w-3.5 shrink-0" />
                <span>{{ opt.label }}</span>
              </button>
            </div>
          </div>

          <button
            type="button"
            class="focus-ring mt-3.5 flex w-full items-center justify-between rounded-xl bg-surface px-3 py-2.5 text-[13.5px] font-medium text-fg transition-colors hover:bg-hover"
            @click="goToSettings"
          >
            <span class="flex items-center gap-2">
              <AppIcon name="settings" class="h-4 w-4 text-fg-muted" :stroke-width="1.85" />
              <span>打开设置</span>
            </span>
            <AppIcon name="chevron-right" class="h-4 w-4 text-fg-faint" />
          </button>
        </div>
      </Transition>
    </Teleport>

    <!-- Teleported Rail Tooltip -->
    <Teleport to="body">
      <div
        v-if="tooltip && isDesktop"
        class="pointer-events-none fixed z-50 -translate-y-1/2 rounded-xl bg-fg px-2.5 py-1.5 text-canvas shadow-md"
        :style="{ top: `${tooltip.top}px`, left: `${tooltip.left}px` }"
      >
        <p class="whitespace-nowrap text-[12.5px] font-medium leading-tight">{{ tooltip.title }}</p>
        <p v-if="tooltip.sub" class="mt-0.5 whitespace-nowrap text-[11px] opacity-75">{{ tooltip.sub }}</p>
      </div>
    </Teleport>
  </div>
</template>
