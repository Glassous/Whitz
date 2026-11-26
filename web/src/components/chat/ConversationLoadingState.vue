<script setup lang="ts">
defineProps<{
  bottomInset?: number;
}>();
</script>

<template>
  <div
    role="status"
    aria-live="polite"
    aria-busy="true"
    class="flex h-full flex-col justify-between overflow-hidden px-4 pt-20 sm:px-6"
    :style="{ paddingBottom: `${Math.max(148, (bottomInset ?? 0) + 24)}px` }"
  >
    <div class="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-6 py-6">
      <div class="flex flex-col items-center gap-3 text-center">
        <progress aria-label="正在加载对话" class="loading-spinner" />
        <p class="text-[13.5px] font-medium text-fg-muted">正在加载对话…</p>
      </div>

      <div class="mx-auto flex w-full max-w-2xl flex-col gap-5 opacity-70" aria-hidden="true">
        <div class="flex justify-end">
          <div class="skeleton-pulse h-10 w-44 rounded-2xl bg-surface sm:w-56" />
        </div>
        <div class="flex flex-col gap-2.5">
          <div class="skeleton-pulse h-4 w-3/4 rounded-lg bg-surface" />
          <div class="skeleton-pulse h-4 w-full rounded-lg bg-surface" />
          <div class="skeleton-pulse h-4 w-2/3 rounded-lg bg-surface" />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@media (prefers-reduced-motion: no-preference) {
  .skeleton-pulse {
    animation: skeleton-fade 1.8s ease-in-out infinite;
  }
}

@keyframes skeleton-fade {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 0.9;
  }
}
</style>
