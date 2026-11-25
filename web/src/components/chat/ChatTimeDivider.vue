<script setup lang="ts">
defineProps<{
  datetime: string;
  label: string;
}>();
</script>

<template>
  <div class="flex justify-center">
    <time
      :datetime="datetime"
      class="rounded-full bg-surface/75 px-2.5 py-0.5 text-[11.5px] font-medium tabular-nums text-fg-faint select-none dark:bg-surface/65"
    >
      {{ label }}
    </time>
  </div>
</template>
