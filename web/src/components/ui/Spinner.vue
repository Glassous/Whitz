<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 20 });
</script>

<template>
  <svg
    class="whitz-spinner shrink-0"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
  >
    <circle class="opacity-20" cx="12" cy="12" r="9.5" stroke="currentColor" stroke-width="2.6" />
    <path
      class="opacity-90"
      stroke="currentColor"
      stroke-width="2.6"
      stroke-linecap="round"
      d="M12 2.5a9.5 9.5 0 0 1 9.5 9.5"
    />
  </svg>
</template>
