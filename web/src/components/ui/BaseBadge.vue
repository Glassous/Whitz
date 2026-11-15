<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{ tone?: "gray" | "green" | "red" | "brand" | "amber" | "blue" }>(),
  { tone: "gray" },
);

const classes = computed(() => {
  const tones = {
    gray: "bg-surface text-fg-muted",
    green: "bg-success-weak text-success",
    red: "bg-danger-weak text-danger",
    brand: "bg-accent-weak text-accent",
    amber: "bg-warning-weak text-warning",
    blue: "bg-accent-weak text-accent",
  };
  return `inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${tones[props.tone]}`;
});
</script>

<template>
  <span :class="classes"><slot /></span>
</template>
