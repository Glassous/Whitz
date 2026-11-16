<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import Icon from "../components/ui/Icon.vue";
import ThemeToggle from "../components/ui/ThemeToggle.vue";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const nav = [
  { name: "overview", label: "概览", icon: "overview" },
  { name: "users", label: "用户", icon: "users" },
  { name: "invite-codes", label: "邀请码", icon: "ticket" },
  { name: "audit", label: "审计日志", icon: "audit" },
] as const;

const initials = computed(() => (auth.user?.display_name || auth.user?.email || "A").slice(0, 1).toUpperCase());

function isActive(name: string): boolean {
  return route.name === name;
}

async function logout() {
  await auth.logout();
  await router.push({ name: "login" });
}
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-canvas">
    <aside class="hidden w-[232px] shrink-0 flex-col border-r border-line bg-sidebar md:flex">
      <div class="flex h-14 items-center gap-2.5 px-4">
        <div class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-primary text-primary-fg">
          <span class="text-[13px] font-semibold tracking-tight">W</span>
        </div>
        <div class="min-w-0">
          <p class="text-[13.5px] font-semibold leading-tight tracking-tight text-fg">Whitz</p>
          <p class="text-[10.5px] text-fg-faint">管理后台</p>
        </div>
      </div>

      <nav class="flex-1 space-y-0.5 px-2 py-3">
        <router-link
          v-for="item in nav"
          :key="item.name"
          :to="{ name: item.name }"
          class="focus-ring flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors"
          :class="isActive(item.name) ? 'bg-active font-medium text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
        >
          <Icon :name="item.icon" :size="16" />
          {{ item.label }}
        </router-link>
      </nav>

      <div class="border-t border-line p-2">
        <div class="flex items-center gap-2 rounded-xl px-2 py-2">
          <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-[12px] font-semibold text-fg">
            {{ initials }}
          </div>
          <div class="min-w-0 flex-1">
            <p class="truncate text-[13px] font-medium text-fg">{{ auth.user?.display_name }}</p>
            <p class="truncate text-[11px] text-fg-faint">{{ auth.user?.email }}</p>
          </div>
          <ThemeToggle />
        </div>
        <button
          class="focus-ring mt-0.5 flex h-8 w-full items-center justify-center gap-1.5 rounded-lg text-[12px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="logout"
        >
          <Icon name="logout" :size="14" />
          退出登录
        </button>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4 md:hidden">
        <div class="flex h-8 w-8 items-center justify-center rounded-[10px] bg-primary text-primary-fg">
          <span class="text-[13px] font-semibold tracking-tight">W</span>
        </div>
        <div class="min-w-0">
          <p class="text-[13.5px] font-semibold leading-tight text-fg">Whitz</p>
          <p class="text-[10.5px] text-fg-faint">管理后台</p>
        </div>
        <div class="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <button
            class="focus-ring flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            aria-label="退出登录"
            @click="logout"
          >
            <Icon name="logout" :size="16" />
          </button>
        </div>
      </header>

      <nav class="flex gap-1 overflow-x-auto border-b border-line px-2 py-1.5 md:hidden">
        <router-link
          v-for="item in nav"
          :key="item.name"
          :to="{ name: item.name }"
          class="focus-ring flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-[12.5px] transition-colors"
          :class="isActive(item.name) ? 'bg-active font-medium text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
        >
          <Icon :name="item.icon" :size="15" />
          {{ item.label }}
        </router-link>
      </nav>

      <main class="flex-1 overflow-y-auto">
        <div class="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
          <router-view />
        </div>
      </main>
    </div>
  </div>
</template>
