<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string;
    placeholder?: string;
    rows?: number;
    error?: string | null;
    disabled?: boolean;
  }>(),
  { rows: 4, disabled: false },
);

const model = defineModel<string>({ default: "" });
</script>

<template>
  <label class="block">
    <span v-if="label" class="mb-1.5 block text-[14px] font-medium text-fg-muted">{{ label }}</span>
    <textarea
      v-model="model"
      :rows="rows"
      :placeholder="placeholder"
      :disabled="disabled"
      class="focus-ring w-full resize-y rounded-xl border bg-canvas px-3.5 py-3 text-[15px] leading-relaxed text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong disabled:opacity-60"
      :class="error ? 'border-danger' : 'border-line'"
    />
    <span v-if="error" class="mt-1 block text-[13px] text-danger">{{ error }}</span>
  </label>
</template>
