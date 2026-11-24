<script setup lang="ts">
import { useTheme } from "../../lib/theme";
import AppIcon from "./AppIcon.vue";

const { theme, toggle } = useTheme();
</script>

<template>
  <button
    type="button"
    class="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
    :aria-label="theme === 'dark' ? '切换到亮色主题' : '切换到暗色主题'"
    :title="theme === 'dark' ? '切换到亮色主题' : '切换到暗色主题'"
    @click="toggle()"
  >
    <Transition name="whitz-icon-swap" mode="out-in">
      <AppIcon v-if="theme === 'dark'" key="sun" name="sun" class="h-[18px] w-[18px]" :stroke-width="1.8" />
      <AppIcon v-else key="moon" name="moon" class="h-[18px] w-[18px]" :stroke-width="1.8" />
    </Transition>
  </button>
</template>
