<script setup lang="ts">
import { inject } from "vue";
import { useRouter } from "vue-router";
import ScheduledTasksPanel from "../components/schedules/ScheduledTasksPanel.vue";
import AppIcon from "../components/ui/AppIcon.vue";
import { APP_SHELL_KEY } from "../layouts/AppShellLayout.vue";

const router = useRouter();
const shell = inject(APP_SHELL_KEY, null);

function openConversation(id: string) {
  void router.push({ name: "chat-conversation", params: { id } });
}
</script>

<template>
  <div class="relative flex min-w-0 flex-1 flex-col bg-canvas">
    <div class="flex shrink-0 items-center gap-2.5 border-b border-line/60 px-4 py-3 sm:px-6">
      <button
        type="button"
        class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg md:hidden"
        aria-label="打开导航"
        @click="shell?.openMobileNav()"
      >
        <AppIcon name="menu-lines" class="h-[20px] w-[20px]" :stroke-width="2.1" />
      </button>
      <h1 class="min-w-0 truncate text-[16px] font-semibold text-fg">定时任务</h1>
    </div>
    <div v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 lg:px-8">
      <div class="mx-auto w-full max-w-5xl">
        <ScheduledTasksPanel @open-conversation="openConversation" />
      </div>
    </div>
  </div>
</template>
