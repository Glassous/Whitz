<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { WorkApprovalChoice, WorkClarifyQuestion } from "@shared/work-types";
import BaseButton from "@web/components/ui/BaseButton.vue";

const props = defineProps<{
  kind: "approval" | "clarify";
  requestId: string;
  tool: string | null;
  preview: unknown;
  choices?: string[] | null;
  patterns?: string[];
  alwaysPatterns?: string[];
  metadata?: Record<string, unknown> | null;
  questions?: WorkClarifyQuestion[] | null;
  queueCount?: number;
}>();

const emit = defineEmits<{
  approve: [payload: { choice: WorkApprovalChoice; message?: string }];
  clarify: [answers: string[][]];
  rejectClarify: [];
}>();

// ---- Approval state ----
const rejectOpen = ref(false);
const rejectReason = ref("");

const approvalOptions = computed<Array<{ choice: WorkApprovalChoice; label: string; variant: "primary" | "secondary" | "ghost" }>>(() => {
  const allowed = props.choices?.length ? new Set(props.choices) : new Set(["once", "always", "deny"]);
  const all: Array<{ choice: WorkApprovalChoice; label: string; variant: "primary" | "secondary" | "ghost" }> = [
    { choice: "once", label: "允许一次", variant: "primary" },
    { choice: "always", label: "始终允许", variant: "secondary" },
    { choice: "deny", label: "拒绝", variant: "ghost" },
  ];
  return all.filter((opt) => allowed.has(opt.choice));
});

const commandPreview = computed<string | null>(() => {
  if (props.metadata && typeof props.metadata.command === "string") return props.metadata.command;
  if (props.patterns?.length) return props.patterns.join("\n");
  return null;
});

const fallbackPreviewText = computed(() => {
  if (commandPreview.value) return commandPreview.value;
  const value = props.preview;
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
});

function handleApproveClick(choice: WorkApprovalChoice) {
  if (choice === "deny" && !rejectOpen.value) {
    rejectOpen.value = true;
    return;
  }
  emit("approve", { choice, message: choice === "deny" ? rejectReason.value.trim() || undefined : undefined });
  rejectOpen.value = false;
  rejectReason.value = "";
}

function submitDeny() {
  emit("approve", { choice: "deny", message: rejectReason.value.trim() || undefined });
  rejectOpen.value = false;
  rejectReason.value = "";
}

// ---- Multi-question Clarify state (mirrors Web ClarifyCard.vue + OpenCode QuestionRequest) ----
const normalizedQuestions = computed<WorkClarifyQuestion[]>(() => {
  if (Array.isArray(props.questions) && props.questions.length > 0) {
    return props.questions;
  }
  const fallback = typeof props.preview === "string" && props.preview.trim() ? props.preview.trim() : "请补充必要信息后继续。";
  return [
    {
      id: "q_0",
      question: fallback,
      options: (props.choices ?? []).map((label) => ({ label })),
      multiple: false,
      custom: true,
    },
  ];
});

const isMultiQuestion = computed(() => normalizedQuestions.value.length > 1);
const selectedById = ref<Record<string, string[]>>({});
const textById = ref<Record<string, string>>({});

watch(
  () => [props.requestId, normalizedQuestions.value.map((q) => q.id).join(",")],
  () => {
    rejectOpen.value = false;
    rejectReason.value = "";
    const nextSel: Record<string, string[]> = {};
    const nextTxt: Record<string, string> = {};
    for (const q of normalizedQuestions.value) {
      nextSel[q.id] = [];
      nextTxt[q.id] = "";
    }
    selectedById.value = nextSel;
    textById.value = nextTxt;
  },
  { immediate: true },
);

function isSelected(qid: string, label: string): boolean {
  return (selectedById.value[qid] ?? []).includes(label);
}

function toggleOption(q: WorkClarifyQuestion, label: string) {
  const cur = selectedById.value[q.id] ?? [];
  if (q.multiple) {
    const next = cur.includes(label) ? cur.filter((x) => x !== label) : [...cur, label];
    selectedById.value = { ...selectedById.value, [q.id]: next };
  } else {
    const next = cur.includes(label) ? [] : [label];
    selectedById.value = { ...selectedById.value, [q.id]: next };
  }
}

function isQuestionAnswered(q: WorkClarifyQuestion): boolean {
  return (selectedById.value[q.id]?.length ?? 0) > 0 || Boolean((textById.value[q.id] ?? "").trim());
}

const answeredCount = computed(() => normalizedQuestions.value.filter(isQuestionAnswered).length);
const canSubmitClarify = computed(() => answeredCount.value > 0);

function submitClarify() {
  if (!canSubmitClarify.value) return;
  const answers: string[][] = normalizedQuestions.value.map((q) => {
    const picked = [...(selectedById.value[q.id] ?? [])];
    const custom = (textById.value[q.id] ?? "").trim();
    if (custom) picked.push(custom);
    return picked;
  });
  emit("clarify", answers);
}

function onClarifyKeydown(e: KeyboardEvent) {
  if (e.isComposing || e.key !== "Enter") return;
  if (e.metaKey || e.ctrlKey) {
    e.preventDefault();
    submitClarify();
  }
}
</script>

<template>
  <div
    class="animate-rise w-full rounded-2xl border border-line/80 bg-canvas p-4 dark:bg-[#1a1a19]"
    style="box-shadow: var(--shadow)"
  >
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <span class="h-1.5 w-1.5 rounded-full" style="background: var(--work-accent)" />
        <p class="text-[11.5px] font-medium uppercase tracking-[0.14em] text-fg-faint">
          {{ kind === "approval" ? "需要授权执行" : "OpenCode 需要你的补充信息" }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span
          v-if="kind === 'clarify' && isMultiQuestion"
          class="rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-medium tabular-nums text-fg-muted"
        >
          已答 {{ answeredCount }} / {{ normalizedQuestions.length }}
        </span>
        <span
          v-if="queueCount && queueCount > 1"
          class="rounded-full bg-surface px-2 py-0.5 text-[11px] font-medium tabular-nums text-fg-muted"
        >
          还有 {{ queueCount }} 项待确认
        </span>
      </div>
    </div>

    <!-- Approval UI -->
    <template v-if="kind === 'approval'">
      <p class="mt-2 text-[13.5px] text-fg">
        OpenCode 请求执行 <span class="rounded bg-surface px-1.5 py-0.5 font-mono text-[12.5px] font-semibold">{{ tool ?? "工具" }}</span>
      </p>

      <pre
        v-if="fallbackPreviewText"
        class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-code px-3 py-2 font-mono text-[11.5px] leading-relaxed text-[#e6e5e0]"
      >{{ fallbackPreviewText }}</pre>

      <div v-if="alwaysPatterns?.length" class="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-fg-faint">
        <span>「始终允许」将放行规则：</span>
        <code
          v-for="pat in alwaysPatterns.slice(0, 4)"
          :key="pat"
          class="rounded bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted"
        >
          {{ pat }}
        </code>
      </div>

      <div v-if="rejectOpen" class="mt-3 space-y-2 rounded-xl bg-surface/80 p-3">
        <input
          v-model="rejectReason"
          type="text"
          placeholder="可选：说明拒绝原因或告诉 OpenCode 改用其他方案…"
          class="focus-ring w-full rounded-xl bg-canvas px-3 py-2 text-[12.5px] text-fg outline-none placeholder:text-fg-faint"
          @keydown.enter.prevent="submitDeny"
        />
        <div class="flex items-center justify-end gap-2">
          <BaseButton size="sm" variant="ghost" @click="rejectOpen = false">取消</BaseButton>
          <BaseButton size="sm" variant="danger" @click="submitDeny">确认拒绝</BaseButton>
        </div>
      </div>

      <div v-else class="mt-3 flex flex-wrap gap-2">
        <BaseButton
          v-for="opt in approvalOptions"
          :key="opt.choice"
          size="sm"
          :variant="opt.variant"
          @click="handleApproveClick(opt.choice)"
        >
          {{ opt.label }}
        </BaseButton>
      </div>
    </template>

    <!-- Multi-question Clarify UI -->
    <form v-else class="mt-2.5" @submit.prevent="submitClarify" @keydown="onClarifyKeydown">
      <div class="max-h-[42vh] space-y-3 overflow-y-auto custom-scrollbar pr-0.5">
        <div
          v-for="(q, idx) in normalizedQuestions"
          :key="q.id"
          :class="isMultiQuestion ? 'rounded-xl bg-surface/65 p-3' : ''"
        >
          <div class="flex items-center gap-2">
            <span
              v-if="q.header"
              class="shrink-0 rounded-md bg-accent-weak px-1.5 py-0.5 text-[10.5px] font-medium text-accent"
            >
              {{ q.header }}
            </span>
            <p class="whitespace-pre-line text-[13px] font-medium leading-relaxed text-fg">
              {{ isMultiQuestion ? `${idx + 1}. ${q.question}` : q.question }}
            </p>
          </div>

          <div v-if="q.options.length" class="mt-2 grid gap-1.5 sm:grid-cols-2">
            <button
              v-for="opt in q.options"
              :key="opt.label"
              type="button"
              :aria-pressed="isSelected(q.id, opt.label)"
              class="focus-ring flex items-start gap-2 rounded-xl border px-3 py-2 text-left transition-colors"
              :class="
                isSelected(q.id, opt.label)
                  ? 'border-[color:var(--work-accent)] bg-[color:var(--work-accent-weak)] text-fg'
                  : 'border-line bg-canvas text-fg-muted hover:border-line-strong hover:text-fg'
              "
              @click="toggleOption(q, opt.label)"
            >
              <span
                class="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center border text-[10px]"
                :class="[
                  q.multiple ? 'rounded-[4px]' : 'rounded-full',
                  isSelected(q.id, opt.label) ? 'border-transparent bg-[color:var(--work-accent)] text-white' : 'border-line-strong',
                ]"
              >
                <svg v-if="isSelected(q.id, opt.label)" class="h-2.5 w-2.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3.5 8.5L6.5 11.5L12.5 4.5" />
                </svg>
              </span>
              <span class="min-w-0 flex-1">
                <span class="block text-[12.5px] font-medium text-fg">{{ opt.label }}</span>
                <span v-if="opt.description" class="mt-0.5 block text-[11px] leading-snug text-fg-faint">{{ opt.description }}</span>
              </span>
            </button>
          </div>

          <div v-if="q.custom !== false || !q.options.length" class="mt-2">
            <input
              v-model="textById[q.id]"
              type="text"
              :placeholder="q.options.length ? '补充说明或输入自定义回答（可选）…' : '输入你的回答…'"
              class="focus-ring h-9 w-full rounded-xl border border-line bg-canvas px-3 text-[12.5px] text-fg outline-none placeholder:text-fg-faint"
            />
          </div>
        </div>
      </div>

      <div class="mt-3 flex items-center justify-between gap-2">
        <button
          type="button"
          class="rounded-lg px-2.5 py-1 text-[12px] text-fg-faint transition-colors hover:bg-hover hover:text-fg"
          @click="emit('rejectClarify')"
        >
          跳过 / 拒绝提问
        </button>
        <div class="flex items-center gap-2">
          <span v-if="isMultiQuestion" class="hidden text-[11px] text-fg-faint sm:inline">Ctrl+Enter 提交</span>
          <BaseButton type="submit" size="sm" :disabled="!canSubmitClarify">提交回答</BaseButton>
        </div>
      </div>
    </form>
  </div>
</template>
