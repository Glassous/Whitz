<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import type { Plan, PlanItem, ReasoningBlock } from "../../types";
import Spinner from "../ui/Spinner.vue";
import ReasoningEntry from "./ReasoningEntry.vue";

const props = defineProps<{
  plan: Plan | null;
  reasoning: ReasoningBlock[];
  streaming: boolean;
  currentStep: { index: number; total: number; title: string } | null;
  runningTool: string | null;
  turnKey: string;
}>();

const items = computed<PlanItem[]>(() => props.plan?.items ?? []);

function blocksFor(item: PlanItem, index: number): ReasoningBlock[] {
  return props.reasoning.filter((b) => {
    if (b.step == null) return false;
    if (b.step_id != null && item.id != null) return b.step_id === String(item.id);
    return b.step === index;
  });
}

const steps = computed(() =>
  items.value.map((item, idx) => ({
    item,
    index: idx + 1,
    blocks: blocksFor(item, idx + 1),
  })),
);

const toggledSteps = ref<Record<string, boolean>>({});

function stepKey(step: { item: PlanItem; index: number }): string {
  return step.item.id != null ? String(step.item.id) : `idx-${step.index}`;
}

function stepOpen(step: { item: PlanItem; index: number }): boolean {
  return toggledSteps.value[stepKey(step)] ?? step.item.status === "in_progress";
}

function toggleStep(step: { item: PlanItem; index: number }) {
  toggledSteps.value = { ...toggledSteps.value, [stepKey(step)]: !stepOpen(step) };
}

function stepMeta(step: { blocks: ReasoningBlock[] }): string {
  const calls = step.blocks.length;
  const tools = step.blocks.reduce((sum, b) => sum + (b.tools?.length ?? 0), 0);
  return [calls ? `${calls} 段思考` : "", tools ? `${tools} 个操作` : ""].filter(Boolean).join(" · ");
}

watch(
  () => props.streaming,
  (val, old) => {
    if (val && !old) toggledSteps.value = {};
  },
);

watch(
  () => props.turnKey,
  async () => {
    toggledSteps.value = {};
    await nextTick();
    if (scrollEl.value) scrollEl.value.scrollTop = 0;
  },
);

const matchedBlocks = computed(() => new Set(steps.value.flatMap((s) => s.blocks)));
const planningBlocks = computed(() => props.reasoning.filter((b) => b.step == null && b.title !== "总结"));
const summaryBlocks = computed(() => props.reasoning.filter((b) => b.step == null && b.title === "总结"));
const looseBlocks = computed(() =>
  items.value.length
    ? props.reasoning.filter((b) => b.step != null && !matchedBlocks.value.has(b))
    : props.reasoning,
);

const done = computed(() => items.value.filter((i) => i.status === "completed").length);
const pct = computed(() => (items.value.length ? Math.round((done.value / items.value.length) * 100) : 0));
const hasContent = computed(() => items.value.length > 0 || props.reasoning.length > 0);

const statusOf = (status: string) =>
  status === "completed" ? "已完成" : status === "in_progress" ? "进行中" : "待执行";

const scrollEl = ref<HTMLElement | null>(null);
const signature = computed(
  () =>
    props.reasoning
      .map((b) => `${b.text.length}:${b.tools?.length ?? 0}:${(b.tools ?? []).map((t) => t.args?.length ?? 0).join(",")}`)
      .join("|") +
    `:${props.streaming}:${items.value.map((i) => i.status).join("")}`,
);

watch(
  signature,
  async () => {
    const el = scrollEl.value;
    if (!el) return;
    const follow = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    await nextTick();
    if (follow) el.scrollTop = el.scrollHeight;
  },
  { flush: "post" },
);
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="flex shrink-0 items-center px-5 pb-2 pt-3.5 lg:pr-14">
      <h3 class="flex h-10 items-center text-[15.5px] font-semibold text-fg">任务面板</h3>
    </div>

    <div ref="scrollEl" v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto pl-4 pr-1.5 pb-4">
      <section v-if="items.length && planningBlocks.length" class="mb-4">
        <h4 class="mb-2 text-[13.5px] font-medium text-fg-muted">规划</h4>
        <div class="space-y-3">
          <div v-for="(block, bi) in planningBlocks" :key="bi">
            <ReasoningEntry :block="block" />
          </div>
        </div>
      </section>

      <section v-if="steps.length" class="mb-4">
        <div class="mb-2 flex items-center justify-between">
          <h4 class="text-[13.5px] font-medium text-fg-muted">执行步骤</h4>
          <span class="text-[12.5px] tabular-nums text-fg-faint">{{ done }} / {{ items.length }}</span>
        </div>
        <div class="mb-3 h-1 overflow-hidden rounded-full bg-surface">
          <div class="h-full rounded-full bg-accent transition-all duration-500" :style="{ width: pct + '%' }" />
        </div>
        <div class="space-y-2">
          <details
            v-for="step in steps"
            :key="stepKey(step)"
            :open="stepOpen(step) && step.blocks.length > 0"
            class="disclosure-card overflow-hidden rounded-xl bg-canvas/75"
          >
            <summary
              class="focus-ring flex w-full items-start gap-2 px-3 py-2.5 text-left"
              :class="step.blocks.length ? 'cursor-pointer' : 'cursor-default'"
              @click.prevent="toggleStep(step)"
            >
              <span class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                <span v-if="step.item.status === 'in_progress'" class="text-accent"><Spinner :size="14" /></span>
                <span
                  v-else-if="step.item.status === 'completed'"
                  class="flex h-4 w-4 items-center justify-center rounded-full bg-success-weak text-success"
                >
                  <svg class="h-2.5 w-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </span>
                <span v-else class="h-3 w-3 rounded-full border-[1.5px] border-line-strong" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="shrink-0 text-[11.5px] font-medium tabular-nums text-fg-faint">步骤 {{ step.index }}</span>
                  <span
                    class="truncate text-[14px] leading-snug"
                    :class="
                      step.item.status === 'completed'
                        ? 'text-fg-faint'
                        : step.item.status === 'in_progress'
                          ? 'font-medium text-fg'
                          : 'text-fg-muted'
                    "
                  >
                    {{ step.item.content }}
                  </span>
                </div>
                <span class="mt-0.5 flex items-center gap-1 text-[12px] text-fg-faint">
                  {{ statusOf(step.item.status) }}
                  <template v-if="!stepOpen(step) && stepMeta(step)"> · {{ stepMeta(step) }}</template>
                </span>
              </div>
              <svg
                v-if="step.blocks.length"
                class="mt-1 h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform duration-200"
                :class="stepOpen(step) ? 'rotate-90' : ''"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
              </svg>
            </summary>

            <div v-if="step.blocks.length" class="space-y-2 px-3 pb-2.5 pt-0.5">
              <ReasoningEntry v-for="(block, bi) in step.blocks" :key="bi" :block="block" />
            </div>
          </details>
        </div>
      </section>

      <section v-if="items.length && summaryBlocks.length" class="mb-4">
        <h4 class="mb-2 text-[13.5px] font-medium text-fg-muted">总结</h4>
        <div class="space-y-2">
          <ReasoningEntry v-for="(block, bi) in summaryBlocks" :key="bi" :block="block" />
        </div>
      </section>

      <section v-if="looseBlocks.length" class="mb-4">
        <h4 class="mb-2 text-[13.5px] font-medium text-fg-muted">
          {{ items.length ? "其他记录" : "思考与执行" }}
        </h4>
        <div class="space-y-3">
          <div v-for="(block, bi) in looseBlocks" :key="bi">
            <ReasoningEntry :block="block" />
          </div>
        </div>
      </section>

      <div v-if="runningTool && streaming" class="mt-1 rounded-lg bg-surface px-3 py-2 text-[12.5px] text-fg-muted">
        正在调用 <span class="font-medium text-fg">{{ runningTool }}</span>
      </div>

      <div v-if="!hasContent && !currentStep" class="flex min-h-full items-center justify-center px-4 text-center">
        <p class="text-[13.5px] leading-relaxed text-fg-faint">
          暂无运行详情。<br />助理处理多步骤任务时，这里会按步骤显示思考与工具调用。
        </p>
      </div>
    </div>
  </div>
</template>
