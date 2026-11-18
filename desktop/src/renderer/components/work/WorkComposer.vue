<script setup lang="ts">
import { computed, ref } from "vue";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  streaming: boolean;
  sending: boolean;
  disabled: boolean;
  disabledReason: string | null;
}>();

const emit = defineEmits<{ send: [string]; stop: [] }>();

const text = ref("");

const canSend = computed(() => !props.disabled && !props.sending && text.value.trim().length > 0);

function submit() {
  if (!canSend.value) return;
  const value = text.value.trim();
  text.value = "";
  emit("send", value);
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <div class="border-t border-line bg-canvas/85 px-6 py-3.5 backdrop-blur">
    <div class="mx-auto max-w-[860px]">
      <div
        class="rounded-2xl border bg-canvas px-3.5 py-2.5 transition-colors"
        :class="disabled ? 'border-line opacity-70' : 'border-line focus-within:border-line-strong'"
      >
        <textarea
          v-model="text"
          rows="1"
          class="chat-textarea block w-full resize-none border-0 bg-transparent text-[14px] leading-relaxed text-fg outline-none placeholder:text-fg-faint"
          :placeholder="disabled ? disabledReason ?? '当前不可用' : streaming ? '智能体正在执行，可先输入下一条…' : '交代任务，或直接提问…'"
          :disabled="disabled"
          @keydown="onKeydown"
        ></textarea>

        <div class="mt-1.5 flex items-center justify-between gap-3">
          <p class="text-[11px] text-fg-faint">
            <span v-if="disabled" class="text-warning">{{ disabledReason }}</span>
            <span v-else>Enter 发送 · Shift+Enter 换行 · 工具执行遵循本机审批设置</span>
          </p>
          <div class="flex items-center gap-2">
            <BaseButton v-if="streaming" size="sm" variant="secondary" @click="emit('stop')">停止</BaseButton>
            <BaseButton size="sm" :disabled="!canSend" @click="submit">发送</BaseButton>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
