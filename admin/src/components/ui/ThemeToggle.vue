<script setup lang="ts">
import { useTheme } from "../../lib/theme";

const { theme, toggle } = useTheme();
</script>

<template>
  <button
    type="button"
    class="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
    :aria-label="theme === 'dark' ? '切换到亮色主题' : '切换到暗色主题'"
    :title="theme === 'dark' ? '切换到亮色主题' : '切换到暗色主题'"
    @click="toggle"
  >
    <svg v-if="theme === 'dark'" class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
      <circle cx="12" cy="12" r="4" />
      <path stroke-linecap="round" d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
    <svg v-else class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
      <path stroke-linecap="round" stroke-linejoin="round" d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
    </svg>
  </button>
</template>
