<script setup lang="ts">
import { nextTick, ref } from "vue";

const props = defineProps<{ streaming: boolean; disabled?: boolean }>();
const emit = defineEmits<{ send: [string]; stop: [] }>();

const text = ref("");
const area = ref<HTMLTextAreaElement | null>(null);

function resize() {
  const el = area.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 208) + "px";
}

function submit() {
  const value = text.value.trim();
  if (!value || props.streaming || props.disabled) return;
  emit("send", value);
  text.value = "";
  nextTick(resize);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    submit();
  }
}
</script>

<template>
  <div>
    <div
      class="flex items-end gap-2 rounded-[26px] bg-surface px-2.5 py-2 transition-colors focus-within:bg-hover/75"
    >
      <textarea
        ref="area"
        v-model="text"
        rows="1"
        :disabled="disabled"
        :placeholder="disabled ? '助理正在初始化，请稍候…' : '给 Whitz 发送消息…'"
        class="max-h-52 min-h-[34px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] leading-relaxed text-fg outline-none placeholder:text-fg-faint disabled:cursor-not-allowed"
        @input="resize"
        @keydown="onKeydown"
      />

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
        class="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-primary-fg transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:bg-surface disabled:text-fg-faint"
        :disabled="!text.trim() || disabled"
        aria-label="发送"
        title="发送"
        @click="submit"
      >
        <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 19V5M6 11l6-6 6 6" />
        </svg>
      </button>
    </div>

    <p class="mt-2 text-center text-[11px] text-fg-faint">Enter 发送 · Shift + Enter 换行 · Whitz 可能会出错，请核对重要信息</p>
  </div>
</template>
