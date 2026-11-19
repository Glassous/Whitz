<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { chromeBack } from "@web/host/chrome";
import { useDesktopStore } from "../../stores/desktop";
import { useWorkStore } from "../../stores/work";

const route = useRoute();
const router = useRouter();
const desktop = useDesktopStore();
const work = useWorkStore();

const inWork = computed(() => typeof route.name === "string" && route.name.startsWith("work"));
const online = computed(() => desktop.online);
const userLabel = computed(() => desktop.user?.display_name ?? "未登录");

function switchTo(target: "chat" | "work") {
  if (target === "work" && !desktop.workEnabled) return;
  void router.push({ name: target === "chat" ? "chat" : "work" });
}

function goAccount() {
  void router.push({ name: desktop.loggedIn ? "settings" : "login" });
}

async function toggleOffline() {
  await desktop.setForcedOffline(!desktop.connectivity.forced_offline);
}
</script>

<template>
  <header class="desktop-titlebar app-drag relative z-50 flex shrink-0 items-center gap-4 border-b border-line/70 bg-canvas/80 px-4 backdrop-blur-xl">
    <div class="no-drag flex items-center">
      <span class="brand-mark-tight h-[11px] w-[17px] text-fg" aria-hidden="true"></span>
      <span class="-ml-[3px] translate-y-[0.5px] select-none text-[13.5px] font-semibold leading-none tracking-tight text-fg">hitz</span>
    </div>

    <button
      v-if="chromeBack"
      type="button"
      class="no-drag focus-ring flex items-center gap-1.5 rounded-full border border-line bg-canvas/60 px-2.5 py-1 text-[12px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
      :title="chromeBack.label"
      @click="chromeBack.run()"
    >
      <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
      </svg>
      <span class="max-w-[150px] truncate">{{ chromeBack.label }}</span>
    </button>

    <div class="no-drag flex items-center rounded-full border border-line bg-surface/70 p-0.5" role="tablist" aria-label="工作模式">
      <button
        type="button"
        role="tab"
        :aria-selected="!inWork"
        class="focus-ring rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="!inWork ? 'bg-canvas text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
        @click="switchTo('chat')"
      >
        Chat
      </button>
      <button
        v-if="desktop.workEnabled"
        type="button"
        role="tab"
        :aria-selected="inWork"
        class="focus-ring flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="inWork ? 'bg-canvas text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
        @click="switchTo('work')"
      >
        <span class="h-1.5 w-1.5 rounded-full" :style="{ background: inWork ? 'var(--work-accent)' : 'var(--line-strong)' }"></span>
        Work
      </button>
    </div>

    <span
      v-if="inWork && work.activeWorkspace"
      class="no-drag hidden max-w-[220px] truncate rounded-full border border-line/80 bg-surface/60 px-2.5 py-0.5 text-[11px] text-fg-muted md:inline-block"
      :title="work.activeWorkspace.path"
    >
      {{ work.activeWorkspace.name }}
    </span>

    <div class="flex-1"></div>

    <div class="no-drag flex items-center gap-3">
      <button
        type="button"
        class="focus-ring flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] transition-colors hover:bg-hover"
        :class="desktop.connectivity.forced_offline ? 'text-warning' : 'text-fg-faint hover:text-fg'"
        :title="desktop.connectivity.forced_offline ? '已强制离线，点击恢复在线' : '在线，点击切换到离线模式'"
        @click="toggleOffline"
      >
        <span
          class="h-1.5 w-1.5 rounded-full"
          :style="{ background: online ? 'var(--success)' : 'var(--fg-faint)' }"
        ></span>
        {{ desktop.connectivity.forced_offline ? "强制离线" : online ? "在线" : "离线" }}
      </button>
      <button
        type="button"
        class="focus-ring flex max-w-[160px] items-center gap-2 rounded-full border border-line px-2.5 py-1 text-[11px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        @click="goAccount"
      >
        <span class="truncate">{{ userLabel }}</span>
      </button>
    </div>
  </header>
</template>
