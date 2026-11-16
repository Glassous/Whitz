<script setup lang="ts">
import { reactive, watch } from "vue";
import BaseInput from "../ui/BaseInput.vue";
import type { SecurityQuestionInput } from "../../types";

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false });

const model = defineModel<SecurityQuestionInput[]>({ default: () => [] });

const PRESETS = [
  "你就读的第一所小学名称？",
  "你母亲的姓名？",
  "你父亲的姓名？",
  "你的出生城市？",
  "你最喜欢的一本书？",
  "你童年最好的朋友名字？",
  "你的第一只宠物名字？",
];
const CUSTOM = "__custom__";

const state = reactive({
  selections: [PRESETS[0], PRESETS[1]] as string[],
  custom: ["", ""] as string[],
  answers: ["", ""] as string[],
});

function questionAt(i: number): string {
  return state.selections[i] === CUSTOM ? state.custom[i] : state.selections[i];
}

watch(
  () => [state.selections, state.custom, state.answers],
  () => {
    model.value = [0, 1].map((i) => ({ question: questionAt(i).trim(), answer: state.answers[i] }));
  },
  { deep: true, immediate: true },
);
</script>

<template>
  <div :class="compact ? 'space-y-2.5' : 'space-y-4'">
    <div
      v-for="i in [0, 1]"
      :key="i"
      class="rounded-xl border border-line bg-surface/40"
      :class="compact ? 'p-3' : 'p-4'"
    >
      <div class="flex items-center justify-between" :class="compact ? 'mb-2' : 'mb-3'">
        <p class="text-[14px] font-medium text-fg">密保问题 {{ i + 1 }}</p>
        <span v-if="compact" class="text-[12px] text-fg-faint">必填</span>
      </div>
      <label class="block">
        <span v-if="!compact" class="mb-1.5 block text-[14px] text-fg-muted">问题</span>
        <select
          v-model="state.selections[i]"
          class="focus-ring w-full rounded-xl border border-line bg-canvas px-3 text-[15px] text-fg transition-colors hover:border-line-strong"
          :class="compact ? 'h-9.5' : 'h-11'"
        >
          <option v-for="p in PRESETS" :key="p" :value="p">{{ p }}</option>
          <option :value="CUSTOM">自定义问题…</option>
        </select>
      </label>
      <div v-if="state.selections[i] === CUSTOM" :class="compact ? 'mt-2' : 'mt-3'">
        <BaseInput v-model="state.custom[i]" :size="compact ? 'sm' : 'md'" placeholder="输入自定义问题" />
      </div>
      <div :class="compact ? 'mt-2' : 'mt-3'">
        <BaseInput
          v-model="state.answers[i]"
          :size="compact ? 'sm' : 'md'"
          :label="compact ? undefined : '答案'"
          :placeholder="compact ? '请输入密保答案（用于找回密码）' : '请输入答案（牢记，用于找回密码）'"
        />
      </div>
    </div>
    <p v-if="!compact" class="text-[13px] leading-relaxed text-fg-faint">
      答案将加密存储，用于找回密码。请确保两个问题不同且答案便于记忆。
    </p>
  </div>
</template>
