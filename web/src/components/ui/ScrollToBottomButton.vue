<script setup lang="ts">
const props = defineProps<{
  visible: boolean;
  streaming?: boolean;
  /** Optional scroll container ref so focus isn't lost to <body> if button hides while focused. */
  scrollContainer?: HTMLElement | null;
}>();

const emit = defineEmits<{
  click: [];
}>();

function onFocusOut(e: FocusEvent) {
  if (!props.visible && !e.relatedTarget && props.scrollContainer) {
    props.scrollContainer.focus?.({ preventScroll: true });
  }
}
</script>

<template>
  <Transition
    enter-active-class="transition duration-200 ease-[cubic-bezier(0.22,1,0.36,1)]"
    enter-from-class="translate-y-2 scale-90 opacity-0"
    enter-to-class="translate-y-0 scale-100 opacity-100"
    leave-active-class="transition duration-150 ease-in"
    leave-from-class="translate-y-0 scale-100 opacity-100"
    leave-to-class="translate-y-1.5 scale-90 opacity-0"
  >
    <button
      v-if="visible"
      type="button"
      class="focus-ring inline-flex items-center justify-center rounded-full border border-line-strong/85 bg-canvas/80 text-fg shadow-md backdrop-blur-md transition-all duration-150 hover:bg-surface/95 active:scale-95"
      :class="streaming ? 'h-9 gap-1.5 pl-3.5 pr-2.5 text-[12.5px] font-medium' : 'h-9.5 w-9.5'"
      :aria-label="streaming ? '回到底部查看最新输出' : '回到底部'"
      :title="streaming ? '回到底部查看最新输出' : '回到底部'"
      @click="emit('click')"
      @focusout="onFocusOut"
    >
      <span
        v-if="streaming"
        class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
        aria-hidden="true"
      />
      <span v-if="streaming" class="whitespace-nowrap">新内容</span>
      <svg
        class="h-4.5 w-4.5 shrink-0"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.1"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6" />
      </svg>
    </button>
  </Transition>
</template>
