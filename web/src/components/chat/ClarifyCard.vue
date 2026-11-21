<script setup lang="ts">
import { ref } from "vue";
import type { PendingControl } from "../../types";
import BaseButton from "../ui/BaseButton.vue";

const props = defineProps<{
  control: PendingControl;
  submitting?: boolean;
}>();
const emit = defineEmits<{ submit: [string] }>();
const answer = ref("");

function send() {
  const cleaned = answer.value.trim();
  if (!cleaned || props.submitting) return;
  emit("submit", cleaned);
}
</script>

<template>
  <div class="animate-rise rounded-2xl bg-surface p-4">
    <div class="flex gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-weak text-accent">
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M21 12a8 8 0 01-11.6 7.1L4 20l1-5.2A8 8 0 1121 12z" />
        </svg>
      </div>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-fg">助理需要你澄清</p>
        <p v-if="control.preview" class="mt-1 text-[13px] leading-relaxed text-fg-muted">{{ control.preview }}</p>
        <form class="mt-3 flex items-center gap-2" @submit.prevent="send">
          <input
            v-model="answer"
            :disabled="submitting"
            placeholder="输入你的回答…"
            class="focus-ring h-9 flex-1 rounded-xl bg-canvas px-3 text-[13px] text-fg placeholder:text-fg-faint disabled:opacity-60"
          />
          <BaseButton type="submit" size="sm" :loading="submitting" :disabled="!answer.trim() || submitting">
            {{ submitting ? "提交中…" : "提交" }}
          </BaseButton>
        </form>
      </div>
    </div>
  </div>
</template>
