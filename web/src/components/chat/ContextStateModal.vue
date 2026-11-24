<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../../api/client";
import type { ConversationContextState, ConversationWorkingState } from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  open: boolean;
  conversationId: string | null;
  conversationTitle?: string;
}>();

const emit = defineEmits<{
  close: [];
  "jump-message": [messageId: string];
  "open-memory-settings": [];
}>();

const loading = ref(false);
const saving = ref(false);
const archiving = ref(false);
const error = ref<string | null>(null);
const state = ref<ConversationContextState | null>(null);

const hasWorkingState = computed(() => {
  const ws = state.value?.working_state;
  if (!ws) return false;
  return Boolean(
    ws.active_goals?.length ||
      ws.recent_decisions?.length ||
      ws.open_questions?.length ||
      Object.keys(ws.key_entities || {}).length,
  );
});

async function loadState() {
  if (!props.conversationId) return;
  loading.value = true;
  error.value = null;
  try {
    state.value = await api.get<ConversationContextState>(
      `/conversations/${encodeURIComponent(props.conversationId)}/context-state`,
    );
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "加载上下文记忆状态失败";
  } finally {
    loading.value = false;
  }
}

watch(
  () => [props.open, props.conversationId] as const,
  ([isOpen, cid]) => {
    if (isOpen && cid) {
      void loadState();
    }
  },
);

async function saveWorkingState(nextWs: ConversationWorkingState) {
  if (!props.conversationId || saving.value) return;
  saving.value = true;
  error.value = null;
  try {
    state.value = await api.patch<ConversationContextState>(
      `/conversations/${encodeURIComponent(props.conversationId)}/working-state`,
      { working_state: nextWs },
    );
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "更新工作态失败";
  } finally {
    saving.value = false;
  }
}

function removeGoal(index: number) {
  const ws = state.value?.working_state;
  if (!ws) return;
  void saveWorkingState({
    ...ws,
    active_goals: ws.active_goals.filter((_, i) => i !== index),
  });
}

function removeDecision(index: number) {
  const ws = state.value?.working_state;
  if (!ws) return;
  void saveWorkingState({
    ...ws,
    recent_decisions: ws.recent_decisions.filter((_, i) => i !== index),
  });
}

function removeQuestion(index: number) {
  const ws = state.value?.working_state;
  if (!ws) return;
  void saveWorkingState({
    ...ws,
    open_questions: ws.open_questions.filter((_, i) => i !== index),
  });
}

function removeEntity(key: string) {
  const ws = state.value?.working_state;
  if (!ws) return;
  const nextEntities = { ...ws.key_entities };
  delete nextEntities[key];
  void saveWorkingState({
    ...ws,
    key_entities: nextEntities,
  });
}

async function triggerArchiveNow() {
  if (!props.conversationId || archiving.value) return;
  archiving.value = true;
  error.value = null;
  try {
    state.value = await api.post<ConversationContextState>(
      `/conversations/${encodeURIComponent(props.conversationId)}/archive-episode`,
      {},
    );
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "手动归档失败";
  } finally {
    archiving.value = false;
  }
}

function formatDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}
</script>

<template>
  <BaseModal
    :open="open"
    :title="`上下文记忆状态 · ${conversationTitle || '当前对话'}`"
    width="44rem"
    @close="emit('close')"
  >
    <div class="space-y-4">
      <!-- Top Architecture Summary Strip -->
      <div class="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-surface/80 px-4 py-3 text-[12.5px]">
        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1.5 rounded-full bg-accent-weak px-2.5 py-1 font-medium text-accent transition-opacity hover:opacity-80"
            @click="emit('open-memory-settings')"
          >
            <span>L0 常驻核心记忆</span>
            <span class="tabular-nums font-semibold">{{ state?.pinned_memories_count ?? 0 }}</span>
          </button>
          <BaseBadge tone="gray">L2 已归档情景 {{ state?.episodes.length ?? 0 }} 段</BaseBadge>
        </div>
        <div class="flex items-center gap-1.5">
          <BaseButton variant="soft" size="sm" rounded="full" :loading="archiving" @click="triggerArchiveNow">
            立即归档历史
          </BaseButton>
          <BaseButton variant="ghost" size="sm" rounded="full" :loading="loading" @click="loadState">
            刷新
          </BaseButton>
        </div>
      </div>

      <p v-if="error" class="rounded-xl bg-danger-weak px-3.5 py-2.5 text-[13px] text-danger">
        {{ error }}
      </p>

      <div v-if="loading && !state" class="flex items-center justify-center gap-2 py-10 text-[13.5px] text-fg-muted">
        <Spinner :size="18" />
        <span>正在读取工作记忆与归档时间线…</span>
      </div>

      <template v-else-if="state">
        <!-- L1 Structured Working State -->
        <section class="space-y-3 rounded-2xl border border-line/80 bg-canvas p-4">
          <div class="flex items-center justify-between gap-2">
            <div>
              <h3 class="text-[14px] font-semibold text-fg">L1 结构化工作态（Working State）</h3>
              <p class="text-[11.5px] text-fg-faint">
                随长对话自动增量维护，已完成事项自动退场；点击条目右侧 × 可手动修正。
              </p>
            </div>
            <span v-if="state.working_state_updated_at" class="text-[11px] tabular-nums text-fg-faint">
              更新于 {{ formatDate(state.working_state_updated_at) }}
            </span>
          </div>

          <div v-if="hasWorkingState && state.working_state" class="space-y-3 text-[13px]">
            <div v-if="state.working_state.active_goals.length" class="space-y-1.5">
              <p class="text-[12px] font-medium text-fg-muted">进行中目标与待办</p>
              <div class="space-y-1">
                <div
                  v-for="(g, idx) in state.working_state.active_goals"
                  :key="`g-${idx}`"
                  class="flex items-center justify-between gap-2 rounded-xl bg-surface/75 px-3 py-1.5"
                >
                  <span class="min-w-0 flex-1 text-fg">
                    <span class="mr-1.5 rounded bg-accent-weak px-1.5 py-0.5 text-[10.5px] font-medium text-accent">
                      {{ g.status === "blocked" ? "阻塞" : g.status === "pending" ? "待开始" : "进行中" }}
                    </span>
                    {{ g.title }}
                  </span>
                  <button
                    type="button"
                    class="focus-ring shrink-0 rounded p-1 text-fg-faint hover:bg-hover hover:text-danger"
                    aria-label="移除该目标"
                    title="移除该目标"
                    @click="removeGoal(idx)"
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>

            <div v-if="state.working_state.recent_decisions.length" class="space-y-1.5">
              <p class="text-[12px] font-medium text-fg-muted">近期已拍板决策</p>
              <div class="space-y-1">
                <div
                  v-for="(d, idx) in state.working_state.recent_decisions"
                  :key="`d-${idx}`"
                  class="flex items-start justify-between gap-2 rounded-xl bg-surface/75 px-3 py-1.5"
                >
                  <div class="min-w-0 flex-1">
                    <span class="text-fg">{{ d.decision }}</span>
                    <span v-if="d.reason" class="ml-1 text-[12px] text-fg-muted">（{{ d.reason }}）</span>
                    <span v-if="d.date" class="ml-1.5 text-[11px] text-fg-faint">{{ d.date }}</span>
                  </div>
                  <button
                    type="button"
                    class="focus-ring shrink-0 rounded p-1 text-fg-faint hover:bg-hover hover:text-danger"
                    aria-label="移除该决策"
                    title="移除该决策"
                    @click="removeDecision(idx)"
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>

            <div v-if="state.working_state.open_questions.length" class="space-y-1.5">
              <p class="text-[12px] font-medium text-fg-muted">待决问题</p>
              <div class="space-y-1">
                <div
                  v-for="(q, idx) in state.working_state.open_questions"
                  :key="`q-${idx}`"
                  class="flex items-center justify-between gap-2 rounded-xl bg-surface/75 px-3 py-1.5"
                >
                  <span class="min-w-0 flex-1 text-fg">{{ q }}</span>
                  <button
                    type="button"
                    class="focus-ring shrink-0 rounded p-1 text-fg-faint hover:bg-hover hover:text-danger"
                    aria-label="移除该问题"
                    title="移除该问题"
                    @click="removeQuestion(idx)"
                  >
                    ×
                  </button>
                </div>
              </div>
            </div>

            <div v-if="Object.keys(state.working_state.key_entities || {}).length" class="space-y-1.5">
              <p class="text-[12px] font-medium text-fg-muted">关键实体与参数</p>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="(val, key) in state.working_state.key_entities"
                  :key="key"
                  class="inline-flex items-center gap-1 rounded-full bg-surface px-2.5 py-1 text-[12px] text-fg"
                >
                  <span class="font-medium text-fg-muted">{{ key }}:</span>
                  <span>{{ val }}</span>
                  <button
                    type="button"
                    class="ml-0.5 text-fg-faint hover:text-danger"
                    aria-label="移除实体"
                    @click="removeEntity(String(key))"
                  >
                    ×
                  </button>
                </span>
              </div>
            </div>
          </div>

          <p
            v-else-if="state.rolling_summary"
            class="whitespace-pre-wrap rounded-xl bg-surface/65 p-3 text-[12.5px] leading-relaxed text-fg-muted"
          >
            {{ state.rolling_summary }}
          </p>

          <p v-else class="py-3 text-center text-[12.5px] text-fg-faint">
            当前对话尚在滑动原文窗口内，暂未触发归档压缩；对话超过 8 轮或间隔 4 小时后将自动生成结构化工作态。
          </p>
        </section>

        <!-- L2 Immutable Archived Episodes Timeline -->
        <section class="space-y-2.5">
          <div>
            <h3 class="text-[14px] font-semibold text-fg">L2 不可变情景归档时间线（Episodes）</h3>
            <p class="text-[11.5px] text-fg-faint">
              移出窗口的历史对话会按主题封存为独立档案并向量化，不再被后续压缩覆盖失真，可随时通过 RAG 精准召回与定位原文。
            </p>
          </div>

          <div v-if="!state.episodes.length" class="rounded-2xl border border-dashed border-line px-4 py-6 text-center text-[12.5px] text-fg-faint">
            暂无已封存的历史情景档案。
          </div>

          <div v-else class="max-h-[300px] space-y-2.5 overflow-y-auto pr-1 custom-scrollbar">
            <article
              v-for="ep in state.episodes"
              :key="ep.id"
              class="rounded-2xl border border-line/70 bg-canvas p-3.5 text-[12.5px]"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="shrink-0 rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold tabular-nums text-fg-muted">
                    #{{ ep.episode_index }}
                  </span>
                  <span class="truncate text-[13.5px] font-semibold text-fg">{{ ep.topic }}</span>
                </div>
                <div class="flex shrink-0 items-center gap-2">
                  <span class="text-[11px] tabular-nums text-fg-faint">
                    {{ ep.message_count }} 条 · {{ formatDate(ep.ended_at || ep.created_at) }}
                  </span>
                  <button
                    v-if="ep.start_msg_id"
                    type="button"
                    class="focus-ring rounded-full bg-accent-weak px-2.5 py-0.5 text-[11px] font-medium text-accent transition-opacity hover:opacity-80"
                    @click="emit('jump-message', ep.start_msg_id)"
                  >
                    定位原文
                  </button>
                </div>
              </div>
              <p class="mt-2 leading-relaxed text-fg-muted">{{ ep.summary }}</p>
              <div v-if="ep.entities?.length" class="mt-2 flex flex-wrap gap-1">
                <span
                  v-for="ent in ep.entities"
                  :key="ent"
                  class="rounded-full bg-surface px-2 py-0.5 text-[10.5px] text-fg-muted"
                >
                  {{ ent }}
                </span>
              </div>
            </article>
          </div>
        </section>
      </template>
    </div>

    <template #footer>
      <BaseButton variant="soft" rounded="full" @click="emit('close')">关闭</BaseButton>
    </template>
  </BaseModal>
</template>
