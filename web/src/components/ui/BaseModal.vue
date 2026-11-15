<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";

const props = defineProps<{ open: boolean; title?: string; width?: string }>();
const emit = defineEmits<{ close: [] }>();

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && props.open) emit("close");
}

onMounted(() => document.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => document.removeEventListener("keydown", onKeydown));
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-150 ease-out"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition duration-100 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-[2px] dark:bg-black/60" @click="emit('close')" />
        <div
          class="animate-rise relative z-10 w-full overflow-hidden rounded-2xl border border-line bg-canvas shadow-2xl"
          :style="{ maxWidth: width ?? '32rem', boxShadow: 'var(--shadow)' }"
        >
          <div v-if="title" class="flex items-center justify-between border-b border-line px-5 py-4">
            <h3 class="text-[15px] font-semibold text-fg">{{ title }}</h3>
            <button
              class="focus-ring -mr-1 rounded-lg p-1.5 text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              aria-label="关闭"
              @click="emit('close')"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div class="px-5 py-4"><slot /></div>
          <div v-if="$slots.footer" class="flex justify-end gap-2 border-t border-line px-5 py-4">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
