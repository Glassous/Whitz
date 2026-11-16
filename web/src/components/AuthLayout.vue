<script setup lang="ts">
import ThemeToggle from "./ui/ThemeToggle.vue";

defineProps<{
  title: string;
  subtitle?: string;
  mode?: "login" | "register";
}>();
</script>

<template>
  <div class="relative flex min-h-dvh flex-col overflow-x-hidden bg-canvas">
    <!-- Subtle ambient backdrop -->
    <div class="pointer-events-none fixed inset-0 overflow-hidden">
      <div
        class="absolute left-1/2 top-[-12rem] h-[28rem] w-[42rem] -translate-x-1/2 rounded-full bg-accent-weak/80 blur-3xl dark:opacity-35"
      />
      <div
        class="absolute inset-0 opacity-[0.35] dark:opacity-[0.18]"
        style="
          background-image: radial-gradient(var(--line-strong) 1px, transparent 1px);
          background-size: 28px 28px;
          -webkit-mask-image: radial-gradient(ellipse 65% 55% at 50% 28%, black 10%, transparent 78%);
          mask-image: radial-gradient(ellipse 65% 55% at 50% 28%, black 10%, transparent 78%);
        "
      />
    </div>

    <!-- Top bar -->
    <header class="relative z-10 flex items-center justify-between px-5 py-4 sm:px-8">
      <router-link to="/login" class="focus-ring flex items-center rounded-xl py-1 pr-2">
        <span class="brand-mark-tight h-[16px] w-[24px] text-fg" aria-hidden="true" />
        <span class="ml-[1px] translate-y-[0.5px] text-[22px] font-semibold leading-none tracking-tight text-fg">hitz</span>
      </router-link>
      <ThemeToggle />
    </header>

    <!-- Centered stage -->
    <main class="relative z-10 flex flex-1 items-center justify-center px-4 pb-8 pt-1 sm:px-6">
      <div class="animate-rise w-full max-w-[416px]">
        <div
          class="rounded-[24px] border border-line bg-canvas/95 p-6 backdrop-blur-md sm:p-7"
          style="box-shadow: var(--shadow)"
        >
          <!-- Segmented Login / Register switcher -->
          <div
            v-if="mode"
            class="mb-5 grid grid-cols-2 gap-1 rounded-xl border border-line bg-surface p-1"
          >
            <router-link
              to="/login"
              class="focus-ring flex h-8 items-center justify-center rounded-lg text-[13px] font-medium transition-all"
              :class="
                mode === 'login'
                  ? 'bg-canvas text-fg shadow-xs'
                  : 'text-fg-muted hover:text-fg'
              "
            >
              登录
            </router-link>
            <router-link
              to="/register"
              class="focus-ring flex h-8 items-center justify-center rounded-lg text-[13px] font-medium transition-all"
              :class="
                mode === 'register'
                  ? 'bg-canvas text-fg shadow-xs'
                  : 'text-fg-muted hover:text-fg'
              "
            >
              创建账号
            </router-link>
          </div>

          <div>
            <h1 class="text-[22px] font-semibold leading-tight tracking-tight text-fg">{{ title }}</h1>
            <p v-if="subtitle" class="mt-1 text-[13px] leading-relaxed text-fg-muted">{{ subtitle }}</p>
          </div>

          <div class="mt-5">
            <slot />
          </div>
        </div>

        <div v-if="$slots.footer" class="mt-5 text-center text-[12.5px] text-fg-muted">
          <slot name="footer" />
        </div>
      </div>
    </main>
  </div>
</template>
