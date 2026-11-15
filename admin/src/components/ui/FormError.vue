<script setup lang="ts">
defineProps<{ message?: string | null }>();
</script>

<template>
  <div
    v-if="message"
    role="alert"
    class="animate-rise flex items-start gap-2 rounded-xl border border-danger/25 bg-danger-weak px-3 py-2.5 text-[13px] leading-relaxed text-danger"
  >
    <svg class="mt-0.5 h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9" />
      <path stroke-linecap="round" d="M12 8v5M12 16.5v.01" />
    </svg>
    <span>{{ message }}</span>
  </div>
</template>
