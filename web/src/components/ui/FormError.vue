<script setup lang="ts">
import AppIcon from "./AppIcon.vue";

defineProps<{ message?: string | null }>();
</script>

<template>
  <div
    v-if="message"
    role="alert"
    class="animate-rise flex items-start gap-2 rounded-xl border border-danger/25 bg-danger-weak px-3 py-2.5 text-[13px] leading-relaxed text-danger"
  >
    <AppIcon name="alert-circle" class="mt-0.5 h-4 w-4 shrink-0" :stroke-width="1.95" />
    <span>{{ message }}</span>
  </div>
</template>
