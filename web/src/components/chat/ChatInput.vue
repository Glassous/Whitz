<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps<{ streaming: boolean; disabled?: boolean }>();
const emit = defineEmits<{ send: [string]; stop: [] }>();

const MIN_HEIGHT = 34;
const NORMAL_MAX_HEIGHT = 160;

const text = ref("");
const area = ref<HTMLTextAreaElement | null>(null);
const mirror = ref<HTMLTextAreaElement | null>(null);
const textareaHeight = ref(MIN_HEIGHT);
const canExpand = ref(false);
const expanded = ref(false);

let resizeObserver: ResizeObserver | null = null;

function getExpandedMaxHeight(): number {
  if (typeof window === "undefined") return 380;
  return Math.min(440, Math.max(240, Math.round(window.innerHeight * 0.5)));
}

function updateHeight() {
  const el = mirror.value;
  if (!el) return;
  const contentHeight = Math.max(MIN_HEIGHT, el.scrollHeight);
  canExpand.value = contentHeight > NORMAL_MAX_HEIGHT;
  if (!canExpand.value && expanded.value) {
    expanded.value = false;
  }
  if (expanded.value) {
    const expandedMax = getExpandedMaxHeight();
    textareaHeight.value = Math.min(Math.max(contentHeight, 260), expandedMax);
  } else {
    textareaHeight.value = Math.min(contentHeight, NORMAL_MAX_HEIGHT);
  }
}

function toggleExpand() {
  if (!canExpand.value && !expanded.value) return;
  expanded.value = !expanded.value;
  updateHeight();
  area.value?.focus();
}

function submit() {
  const value = text.value.trim();
  if (!value || props.streaming || props.disabled) return;
  emit("send", value);
  text.value = "";
  expanded.value = false;
  canExpand.value = false;
  void nextTick(updateHeight);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  }
}

watch(text, () => {
  void nextTick(updateHeight);
});

onMounted(() => {
  void nextTick(updateHeight);
  if (typeof ResizeObserver !== "undefined" && mirror.value) {
    resizeObserver = new ResizeObserver(() => {
      updateHeight();
    });
    resizeObserver.observe(mirror.value);
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});
</script>

<template>
  <div>
    <div
      class="flex flex-col rounded-[26px] bg-surface px-3.5 pb-2.5 pt-3 transition-colors focus-within:bg-hover/70"
    >
      <!-- Row 1: Smooth auto-resizing textarea + offscreen measurement mirror -->
      <div class="relative">
        <textarea
          ref="mirror"
          tabindex="-1"
          aria-hidden="true"
          rows="1"
          :value="text"
          class="custom-scrollbar pointer-events-none invisible absolute left-0 top-0 -z-10 block w-full resize-none overflow-hidden px-1 py-0.5 text-[15px] leading-relaxed"
        />
        <textarea
          ref="area"
          v-model="text"
          v-scrollbar
          rows="1"
          :disabled="disabled"
          :placeholder="disabled ? '助理正在初始化，请稍候…' : '给 Whitz 发送消息…'"
          class="custom-scrollbar block w-full resize-none bg-transparent px-1 py-0.5 text-[15px] leading-relaxed text-fg outline-none transition-[height] duration-250 ease-[cubic-bezier(0.22,1,0.36,1)] placeholder:text-fg-faint disabled:cursor-not-allowed"
          :style="{ height: `${textareaHeight}px` }"
          @keydown="onKeydown"
        />
      </div>

      <!-- Row 2: Action bar (right-aligned expand/collapse + send/stop) -->
      <div class="mt-2 flex items-center justify-end gap-1.5">
        <Transition
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="scale-75 opacity-0"
          enter-to-class="scale-100 opacity-100"
          leave-active-class="transition duration-100 ease-in"
          leave-from-class="scale-100 opacity-100"
          leave-to-class="scale-75 opacity-0"
        >
          <button
            v-if="canExpand || expanded"
            type="button"
            class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :aria-label="expanded ? '收起输入框' : '展开输入框'"
            :title="expanded ? '收起输入框' : '加大输入框'"
            @click="toggleExpand"
          >
            <Transition
              mode="out-in"
              enter-active-class="transition duration-150 ease-out"
              enter-from-class="scale-75 opacity-0"
              enter-to-class="scale-100 opacity-100"
              leave-active-class="transition duration-100 ease-in"
              leave-from-class="scale-100 opacity-100"
              leave-to-class="scale-75 opacity-0"
            >
              <svg
                v-if="expanded"
                key="collapse"
                class="h-4.5 w-4.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7" />
              </svg>
              <svg
                v-else
                key="expand"
                class="h-4.5 w-4.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
              </svg>
            </Transition>
          </button>
        </Transition>

        <button
          v-if="streaming"
          type="button"
          class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-canvas text-fg transition-colors hover:bg-hover"
          aria-label="停止生成"
          title="停止生成"
          @click="emit('stop')"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="6" width="12" height="12" rx="2.5" />
          </svg>
        </button>
        <button
          v-else
          type="button"
          class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-fg transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-hover disabled:text-fg-faint"
          :disabled="!text.trim() || disabled"
          aria-label="发送"
          title="发送"
          @click="submit"
        >
          <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>
