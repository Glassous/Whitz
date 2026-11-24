<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "soft" | "ghost" | "danger";
    size?: "sm" | "md" | "lg";
    rounded?: "xl" | "2xl" | "full";
    loading?: boolean;
    disabled?: boolean;
    type?: "button" | "submit";
    block?: boolean;
  }>(),
  { variant: "primary", size: "md", rounded: "xl", loading: false, disabled: false, type: "button", block: false },
);

defineEmits<{ click: [MouseEvent] }>();

const classes = computed(() => {
  const radius = props.rounded === "full" ? "rounded-full" : props.rounded === "2xl" ? "rounded-2xl" : "rounded-xl";
  const base =
    `focus-ring inline-flex select-none items-center justify-center gap-2 ${radius} font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50`;
  const sizes = {
    sm: "h-8.5 px-3 text-[13.5px]",
    md: "h-10 px-4 text-[14.5px]",
    lg: "h-11 px-5 text-[15.5px]",
  };
  const variants = {
    primary: "bg-primary text-primary-fg hover:bg-primary-hover",
    secondary: "border border-line bg-canvas text-fg hover:bg-hover",
    soft: "bg-surface text-fg hover:bg-hover",
    ghost: "text-fg-muted hover:bg-hover hover:text-fg",
    danger: "bg-danger-solid text-white hover:opacity-90",
  };
  return [base, sizes[props.size], variants[props.variant], props.block ? "w-full" : ""].join(" ");
});
</script>

<template>
  <button :type="type" :class="classes" :disabled="disabled || loading" @click="$emit('click', $event)">
    <svg v-if="loading" class="whitz-spinner h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle class="opacity-20" cx="12" cy="12" r="9.5" stroke="currentColor" stroke-width="2.6" />
      <path class="opacity-90" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" d="M12 2.5a9.5 9.5 0 0 1 9.5 9.5" />
    </svg>
    <slot />
  </button>
</template>
