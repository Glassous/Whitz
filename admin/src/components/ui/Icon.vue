<script setup lang="ts">
import { computed } from "vue";

type IconName =
  | "overview"
  | "users"
  | "audit"
  | "ticket"
  | "logout"
  | "search"
  | "refresh"
  | "shield"
  | "chevron-left"
  | "chevron-right"
  | "close"
  | "activity"
  | "alert"
  | "file"
  | "device"
  | "stop";

const props = withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 18 });

const paths: Record<IconName, string> = {
  overview: "M4 13h6V4H4v9zm0 7h6v-5H4v5zm10 0h6v-9h-6v9zm0-16v5h6V4h-6z",
  users: "M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75",
  audit: "M9 5h6M9 12h6M9 19h6M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z",
  ticket: "M4 7h16a1 1 0 011 1v2a2 2 0 000 4v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2a2 2 0 000-4V8a1 1 0 011-1zM14 7v10",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
  refresh: "M20 11a8 8 0 10-2.3 6.3M20 4v7h-7",
  shield: "M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z",
  "chevron-left": "M15 18l-6-6 6-6",
  "chevron-right": "M9 18l6-6-6-6",
  close: "M6 6l12 12M18 6L6 18",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  alert: "M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z",
  file: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6",
  device: "M4 6a2 2 0 012-2h12a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM2 20h20M12 16v4",
  stop: "M12 22a10 10 0 100-20 10 10 0 000 20zM9 9h6v6H9z",
};

const d = computed(() => paths[props.name]);
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    aria-hidden="true"
  >
    <path stroke-linecap="round" stroke-linejoin="round" :d="d" />
  </svg>
</template>
