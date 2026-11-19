<script setup lang="ts">
import { computed, ref } from "vue";
import type { WorkApprovalChoice } from "@shared/work-types";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  kind: "approval" | "clarify";
  tool: string | null;
  preview: unknown;
  choices?: string[] | null;
}>();

const emit = defineEmits<{
  approve: [WorkApprovalChoice];
  clarify: [string];
}>();

const answer = ref("");

const approvalOptions = computed<Array<{ choice: WorkApprovalChoice; label: string; variant: "primary" | "secondary" | "ghost" }>>(() => {
  const allowed = props.choices?.length ? new Set(props.choices) : new Set(["once", "session", "always", "deny"]);
  const all: Array<{ choice: WorkApprovalChoice; label: string; variant: "primary" | "secondary" | "ghost" }> = [
    { choice: "once", label: "允许一次", variant: "primary" },
    { choice: "session", label: "本次会话允许", variant: "secondary" },
    { choice: "always", label: "始终允许", variant: "secondary" },
    { choice: "deny", label: "拒绝", variant: "ghost" },
  ];
  return all.filter((opt) => allowed.has(opt.choice));
});

const previewText = computed(() => {
  const value = props.preview;
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
});

function submitClarify(val?: string) {
  const text = (val ?? answer.value).trim();
  if (!text) return;
  answer.value = "";
  emit("clarify", text);
}
</script>

<template>
  <div class="pointer-events-none fixed inset-x-0 bottom-7 z-40 flex justify-center px-6">
    <div class="pointer-events-auto w-full max-w-[720px] rounded-2xl border border-line bg-canvas p-4 shadow-[var(--shadow)]">
      <div class="flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)"></span>
        <p class="text-[12px] font-medium uppercase tracking-[0.14em] text-fg-faint">
          {{ kind === "approval" ? "本地执行审批" : "需要你的补充信息" }}
        </p>
      </div>

      <template v-if="kind === 'approval'">
        <p class="mt-2 text-[13.5px] text-fg">
          OpenCode 请求执行 <span class="font-semibold">{{ tool ?? "工具" }}</span>
        </p>
        <pre
          v-if="previewText"
          class="mt-2 max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code px-3 py-2 font-mono text-[11.5px] leading-relaxed text-[#d6d5ce]"
        >{{ previewText }}</pre>
        <div class="mt-3.5 flex flex-wrap gap-2">
          <BaseButton
            v-for="opt in approvalOptions"
            :key="opt.choice"
            size="sm"
            :variant="opt.variant"
            @click="emit('approve', opt.choice)"
          >
            {{ opt.label }}
          </BaseButton>
        </div>
      </template>

      <template v-else>
        <p class="mt-2 text-[13.5px] text-fg">{{ previewText || "请补充必要信息后继续。" }}</p>
        <div v-if="choices?.length" class="mt-3 flex flex-wrap gap-2">
          <BaseButton
            v-for="option in choices"
            :key="option"
            size="sm"
            variant="secondary"
            @click="submitClarify(option)"
          >
            {{ option }}
          </BaseButton>
        </div>
        <form class="mt-3 flex items-end gap-2" @submit.prevent="submitClarify()">
          <input
            v-model="answer"
            type="text"
            class="focus-ring min-w-0 flex-1 rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] text-fg placeholder:text-fg-faint"
            placeholder="输入补充回答"
          />
          <BaseButton type="submit" size="sm" :disabled="!answer.trim()">提交</BaseButton>
        </form>
      </template>
    </div>
  </div>
</template>
