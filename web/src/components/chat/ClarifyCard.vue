<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ClarifyAnswerItem, ClarifyQuestionItem, ClarifySubmitPayload, PendingControl } from "../../types";
import BaseButton from "../ui/BaseButton.vue";
import AppIcon from "../ui/AppIcon.vue";

const props = defineProps<{
  control: PendingControl;
  submitting?: boolean;
}>();
const emit = defineEmits<{ submit: [ClarifySubmitPayload] }>();

const selectedById = ref<Record<string, string[]>>({});
const textById = ref<Record<string, string>>({});

const questions = computed<ClarifyQuestionItem[]>(() => {
  const list = props.control.clarify?.questions;
  if (Array.isArray(list) && list.length > 0) return list;
  const fallback = props.control.clarify?.question ?? props.control.preview ?? "请补充更多信息以便继续。";
  return [
    {
      id: "q1",
      question: fallback,
      options: props.control.clarify?.options ?? [],
      multiple: Boolean(props.control.clarify?.multiple),
      allow_custom: true,
      placeholder: null,
    },
  ];
});

const isMultiQuestion = computed(() => questions.value.length > 1);

const introText = computed(() => {
  if (!isMultiQuestion.value) return "";
  const raw = (props.control.clarify?.question ?? props.control.preview ?? "").trim();
  if (!raw || raw === questions.value[0]?.question) return "";
  return raw;
});

watch(
  () => [props.control.request_id, props.control.execution_generation, questions.value.map((q) => q.id).join(",")],
  () => {
    const nextSelected: Record<string, string[]> = {};
    const nextText: Record<string, string> = {};
    for (const q of questions.value) {
      nextSelected[q.id] = [];
      nextText[q.id] = "";
    }
    selectedById.value = nextSelected;
    textById.value = nextText;
  },
  { immediate: true },
);

function isSelected(qid: string, option: string): boolean {
  return (selectedById.value[qid] ?? []).includes(option);
}

function toggleOption(q: ClarifyQuestionItem, option: string) {
  if (props.submitting) return;
  const current = selectedById.value[q.id] ?? [];
  if (q.multiple) {
    const next = current.includes(option) ? current.filter((item) => item !== option) : [...current, option];
    selectedById.value = { ...selectedById.value, [q.id]: next };
  } else {
    const next = current.includes(option) ? [] : [option];
    selectedById.value = { ...selectedById.value, [q.id]: next };
  }
}

function formatQuestionTitle(q: ClarifyQuestionItem, index: number): string {
  const text = q.question.trim();
  if (!isMultiQuestion.value) return text;
  if (/^\d+[.、)）]\s*/.test(text)) return text;
  return `${index + 1}. ${text}`;
}

function isQuestionAnswered(q: ClarifyQuestionItem): boolean {
  const hasSel = (selectedById.value[q.id]?.length ?? 0) > 0;
  const hasText = (textById.value[q.id] ?? "").trim().length > 0;
  return hasSel || hasText;
}

const answeredCount = computed(() => questions.value.filter(isQuestionAnswered).length);
const canSubmit = computed(() => !props.submitting && answeredCount.value > 0);

function buildPayload(): ClarifySubmitPayload | null {
  if (!canSubmit.value) return null;
  const answers: ClarifyAnswerItem[] = [];
  const formattedLines: string[] = [];

  questions.value.forEach((q, idx) => {
    const selected = [...(selectedById.value[q.id] ?? [])];
    const text = (textById.value[q.id] ?? "").trim();
    answers.push({
      id: q.id,
      question: q.question,
      selected,
      text,
    });

    if (selected.length === 0 && !text) return;

    let combined = "";
    if (selected.length > 0 && text) {
      combined = `${selected.join("、")}（${text}）`;
    } else if (selected.length > 0) {
      combined = selected.join("、");
    } else {
      combined = text;
    }

    if (isMultiQuestion.value) {
      formattedLines.push(`${idx + 1}. ${q.question}\n答：${combined}`);
    } else {
      formattedLines.push(combined);
    }
  });

  const answer = formattedLines.join("\n\n").trim();
  if (!answer) return null;
  return { answer, answers };
}

function send() {
  const payload = buildPayload();
  if (!payload) return;
  emit("submit", payload);
}

function onSingleTextareaKeydown(e: KeyboardEvent) {
  if (e.isComposing || e.key !== "Enter" || e.shiftKey) return;
  e.preventDefault();
  send();
}

function onFormKeydown(e: KeyboardEvent) {
  if (e.isComposing || e.key !== "Enter") return;
  if (e.metaKey || e.ctrlKey) {
    e.preventDefault();
    send();
  }
}
</script>

<template>
  <div class="animate-rise rounded-2xl border border-line bg-surface p-4 shadow-sm">
    <div class="flex gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-weak text-accent">
        <AppIcon name="message-dots" class="h-4 w-4" :stroke-width="1.95" />
      </div>

      <form class="min-w-0 flex-1" @submit.prevent="send" @keydown="onFormKeydown">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="text-sm font-semibold text-fg">助理需要你澄清</p>
          <span
            v-if="isMultiQuestion"
            class="rounded-full bg-canvas px-2.5 py-0.5 text-[11.5px] font-medium tabular-nums text-fg-muted"
          >
            已答 {{ answeredCount }} / {{ questions.length }}
          </span>
        </div>

        <p v-if="introText" class="mt-1 whitespace-pre-line text-[13px] leading-relaxed text-fg-muted">
          {{ introText }}
        </p>

        <div class="mt-3 max-h-[46vh] space-y-3 overflow-y-auto pr-0.5">
          <div
            v-for="(q, idx) in questions"
            :key="q.id"
            :class="isMultiQuestion ? 'rounded-xl bg-canvas/75 p-3' : ''"
          >
            <p class="whitespace-pre-line text-[13px] font-medium leading-relaxed text-fg">
              {{ formatQuestionTitle(q, idx) }}
            </p>

            <div v-if="q.options.length" class="mt-2 flex flex-wrap gap-1.5">
              <button
                v-for="opt in q.options"
                :key="opt"
                type="button"
                :disabled="submitting"
                :aria-pressed="isSelected(q.id, opt)"
                class="focus-ring inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-left text-[12.5px] transition-colors disabled:opacity-60"
                :class="
                  isSelected(q.id, opt)
                    ? 'border-accent bg-accent-weak font-medium text-accent'
                    : 'border-line bg-canvas text-fg-muted hover:border-line-strong hover:text-fg'
                "
                @click="toggleOption(q, opt)"
              >
                <span
                  class="flex h-3.5 w-3.5 shrink-0 items-center justify-center border text-[10px]"
                  :class="[
                    q.multiple ? 'rounded-[4px]' : 'rounded-full',
                    isSelected(q.id, opt) ? 'border-accent bg-accent text-white' : 'border-line-strong bg-transparent',
                  ]"
                >
                  <AppIcon v-if="isSelected(q.id, opt)" name="check" motion="check-draw" class="h-2.5 w-2.5" :stroke-width="2.8" />
                </span>
                <span>{{ opt }}</span>
              </button>
            </div>

            <div v-if="q.allow_custom !== false || q.options.length === 0" class="mt-2">
              <textarea
                v-if="!isMultiQuestion && q.options.length === 0"
                v-model="textById[q.id]"
                :disabled="submitting"
                rows="2"
                :placeholder="q.placeholder || '输入你的回答…（Enter 提交，Shift+Enter 换行）'"
                class="focus-ring w-full resize-y rounded-xl border border-line bg-canvas px-3 py-2 text-[13px] leading-relaxed text-fg placeholder:text-fg-faint disabled:opacity-60"
                @keydown="onSingleTextareaKeydown"
              />
              <input
                v-else
                v-model="textById[q.id]"
                type="text"
                :disabled="submitting"
                :placeholder="
                  q.placeholder ||
                  (q.options.length ? '补充说明或填写其他答案（可选）…' : '输入该问题的回答…')
                "
                class="focus-ring h-9 w-full rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg placeholder:text-fg-faint disabled:opacity-60"
              />
            </div>
          </div>
        </div>

        <div class="mt-3 flex items-center justify-between gap-2">
          <span class="text-[11.5px] text-fg-faint">
            {{ isMultiQuestion ? "可先填写已确认的问题，Ctrl/Cmd + Enter 提交" : "" }}
          </span>
          <BaseButton type="submit" size="sm" :loading="submitting" :disabled="!canSubmit">
            {{ submitting ? "提交中…" : "提交" }}
          </BaseButton>
        </div>
      </form>
    </div>
  </div>
</template>
