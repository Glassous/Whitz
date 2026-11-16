<script setup lang="ts">
import { onMounted, ref } from "vue";

const props = withDefaults(
  defineProps<{
    label?: string;
    type?: string;
    placeholder?: string;
    error?: string | null;
    disabled?: boolean;
    autocomplete?: string;
    autofocus?: boolean;
    size?: "sm" | "md";
    rounded?: "xl" | "2xl" | "full";
    soft?: boolean;
  }>(),
  { type: "text", disabled: false, autofocus: false, size: "md", rounded: "xl", soft: false },
);

const model = defineModel<string>({ default: "" });
const input = ref<HTMLInputElement | null>(null);

onMounted(() => {
  if (props.autofocus) input.value?.focus();
});
</script>

<template>
  <label class="block">
    <span v-if="label || $slots['label-action']" class="mb-1.5 flex items-center justify-between gap-3">
      <span class="text-[14px] font-medium text-fg-muted">{{ label }}</span>
      <slot name="label-action" />
    </span>
    <div class="relative">
      <input
        ref="input"
        v-model="model"
        :type="type"
        :placeholder="placeholder"
        :disabled="disabled"
        :autocomplete="autocomplete"
        class="focus-ring w-full border text-[15px] text-fg transition-colors placeholder:text-fg-faint disabled:opacity-60"
        :class="[
          size === 'sm' ? 'h-9.5' : 'h-11',
          rounded === 'full' ? 'rounded-full' : rounded === '2xl' ? 'rounded-2xl' : 'rounded-xl',
          soft ? 'border-transparent bg-surface focus:bg-hover/75' : 'bg-canvas hover:border-line-strong',
          error ? 'border-danger' : soft ? '' : 'border-line',
          $slots.suffix ? 'pl-4 pr-12' : 'px-3.5',
        ]"
      />
      <div v-if="$slots.suffix" class="absolute inset-y-0 right-1.5 flex items-center">
        <slot name="suffix" />
      </div>
    </div>
    <span v-if="error" class="mt-1 block text-[13px] text-danger">{{ error }}</span>
  </label>
</template>
