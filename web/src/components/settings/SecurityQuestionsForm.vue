<script setup lang="ts">
import { reactive, watch } from "vue";
import BaseInput from "../ui/BaseInput.vue";
import type { SecurityQuestionInput } from "../../types";

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
  <div class="space-y-4">
    <div v-for="i in [0, 1]" :key="i" class="rounded-xl border border-line p-4">
      <p class="mb-3 text-[13px] font-medium text-fg">密保问题 {{ i + 1 }}</p>
      <label class="block">
        <span class="mb-1.5 block text-[13px] text-fg-muted">问题</span>
        <select
          v-model="state.selections[i]"
          class="focus-ring h-11 w-full rounded-xl border border-line bg-canvas px-3 text-sm text-fg transition-colors hover:border-line-strong"
        >
          <option v-for="p in PRESETS" :key="p" :value="p">{{ p }}</option>
          <option :value="CUSTOM">自定义问题…</option>
        </select>
      </label>
      <div v-if="state.selections[i] === CUSTOM" class="mt-3">
        <BaseInput v-model="state.custom[i]" placeholder="输入自定义问题" />
      </div>
      <div class="mt-3">
        <BaseInput v-model="state.answers[i]" label="答案" placeholder="请输入答案（牢记，用于找回密码）" />
      </div>
    </div>
    <p class="text-xs leading-relaxed text-fg-faint">答案将加密存储，用于找回密码。请确保两个问题不同且答案便于记忆。</p>
  </div>
</template>
