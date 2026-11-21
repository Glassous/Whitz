<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useSchedulesStore } from "../../stores/schedules";
import type { ScheduledTask, ScheduledTaskRun } from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import FormError from "../ui/FormError.vue";
import Spinner from "../ui/Spinner.vue";
import ScheduleEditorModal from "./ScheduleEditorModal.vue";

const emit = defineEmits<{
  "open-conversation": [string];
}>();

const schedules = useSchedulesStore();

const searchQuery = ref("");
const editorOpen = ref(false);
const editingTask = ref<ScheduledTask | null>(null);
const deleteTarget = ref<ScheduledTask | null>(null);
const deleting = ref(false);
const busyTaskId = ref<string | null>(null);
const busyProposalId = ref<string | null>(null);
const expandedTaskId = ref<string | null>(null);
const loadingRunsId = ref<string | null>(null);
const actionError = ref<string | null>(null);

function extractError(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

const filteredTasks = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return schedules.tasks;
  return schedules.tasks.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      t.prompt.toLowerCase().includes(q) ||
      t.schedule_description.toLowerCase().includes(q),
  );
});

function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusMeta(task: ScheduledTask): { label: string; tone: "green" | "gray" | "red" | "blue" } {
  if (task.last_run_status === "running") return { label: "执行中", tone: "blue" };
  if (task.status === "error") return { label: "异常暂停", tone: "red" };
  if (task.status === "completed") return { label: "已完成", tone: "gray" };
  if (!task.enabled || task.status === "paused") return { label: "已暂停", tone: "gray" };
  return { label: "运行中", tone: "green" };
}

function runStatusMeta(run: ScheduledTaskRun): { label: string; cls: string } {
  switch (run.status) {
    case "completed":
      return { label: "成功", cls: "bg-success-weak text-success" };
    case "failed":
      return { label: "失败", cls: "bg-danger-weak text-danger" };
    case "skipped":
      return { label: "跳过", cls: "bg-warning-weak text-warning" };
    case "cancelled":
      return { label: "已取消", cls: "bg-canvas text-fg-muted" };
    default:
      return { label: "执行中", cls: "bg-accent-weak text-accent" };
  }
}

function targetModeLabel(task: ScheduledTask): string {
  if (task.target_mode === "main") return "主聊天";
  if (task.target_mode === "conversation") return "指定旁聊";
  return "专属旁聊";
}

function openCreate() {
  editingTask.value = null;
  editorOpen.value = true;
}

function openEdit(task: ScheduledTask) {
  editingTask.value = task;
  editorOpen.value = true;
}

async function onToggleEnabled(task: ScheduledTask) {
  if (busyTaskId.value) return;
  busyTaskId.value = task.id;
  actionError.value = null;
  try {
    await schedules.updateTask(task.id, { enabled: !task.enabled });
  } catch (e: any) {
    actionError.value = extractError(e, "切换任务状态失败");
  } finally {
    busyTaskId.value = null;
  }
}

async function onRunNow(task: ScheduledTask) {
  if (busyTaskId.value) return;
  busyTaskId.value = task.id;
  actionError.value = null;
  try {
    await schedules.runNow(task.id);
    expandedTaskId.value = task.id;
    await schedules.fetchDetail(task.id);
  } catch (e: any) {
    actionError.value = extractError(e, "触发定时任务失败");
  } finally {
    busyTaskId.value = null;
  }
}

async function onToggleHistory(task: ScheduledTask) {
  if (expandedTaskId.value === task.id) {
    expandedTaskId.value = null;
    return;
  }
  expandedTaskId.value = task.id;
  loadingRunsId.value = task.id;
  try {
    await schedules.fetchDetail(task.id);
  } finally {
    if (loadingRunsId.value === task.id) loadingRunsId.value = null;
  }
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return;
  deleting.value = true;
  actionError.value = null;
  try {
    await schedules.deleteTask(deleteTarget.value.id);
    deleteTarget.value = null;
  } catch (e: any) {
    actionError.value = extractError(e, "删除定时任务失败");
  } finally {
    deleting.value = false;
  }
}

async function onResolvePending(id: string, action: "approve" | "reject") {
  if (busyProposalId.value) return;
  busyProposalId.value = id;
  actionError.value = null;
  try {
    await schedules.resolvePending(id, action);
  } catch (e: any) {
    actionError.value = extractError(e, "处理提案失败");
  } finally {
    busyProposalId.value = null;
  }
}

onMounted(() => {
  void schedules.fetchAll().catch((e: any) => {
    actionError.value = extractError(e, "加载定时任务失败");
  });
});
</script>

<template>
  <div class="space-y-5">
    <!-- Top Summary & Actions -->
    <div class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line/70 bg-surface p-4">
      <div class="space-y-1">
        <div class="flex items-center gap-2">
          <h2 class="text-[15.5px] font-semibold text-fg">自动化定时任务</h2>
          <BaseBadge tone="brand">
            已启用 {{ schedules.quota.active_count }} / {{ schedules.quota.max_active_tasks }}
          </BaseBadge>
          <span class="text-[12px] text-fg-faint">最小间隔 {{ schedules.quota.min_interval_minutes }} 分钟</span>
        </div>
        <p class="text-[12.5px] text-fg-muted">
          到点后由后台智能体无人值守执行，结果自动推送到对应聊天并计入正常用量。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <input
          v-model="searchQuery"
          type="search"
          placeholder="搜索任务…"
          class="focus-ring h-9 w-44 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg placeholder:text-fg-faint"
        />
        <BaseButton size="sm" @click="openCreate">新建定时任务</BaseButton>
      </div>
    </div>

    <FormError :message="actionError" />

    <!-- Pending AI Proposals -->
    <div v-if="schedules.pending.length" class="space-y-2.5">
      <p class="text-[12.5px] font-medium text-fg-muted">待确认的助理提案 ({{ schedules.pending.length }})</p>
      <div
        v-for="item in schedules.pending"
        :key="item.id"
        class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-accent/30 bg-accent-weak/40 p-3.5"
      >
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[13.5px] font-semibold text-fg">{{ item.payload?.name || "定时任务变更" }}</span>
            <BaseBadge tone="brand">{{ item.action }}</BaseBadge>
            <span v-if="item.schedule_description" class="text-[12px] text-fg-muted">{{ item.schedule_description }}</span>
          </div>
          <p v-if="item.payload?.prompt" class="mt-1 line-clamp-2 text-[12.5px] text-fg-muted">
            {{ item.payload.prompt }}
          </p>
          <p v-if="item.reason" class="mt-0.5 text-[11.5px] text-fg-faint">{{ item.reason }}</p>
        </div>
        <div class="flex gap-2">
          <BaseButton
            size="sm"
            :loading="busyProposalId === item.id"
            @click="onResolvePending(item.id, 'approve')"
          >
            确认生效
          </BaseButton>
          <BaseButton
            size="sm"
            variant="secondary"
            :disabled="busyProposalId === item.id"
            @click="onResolvePending(item.id, 'reject')"
          >
            拒绝
          </BaseButton>
        </div>
      </div>
    </div>

    <!-- Loading / Empty / List -->
    <div v-if="schedules.loading && !schedules.tasks.length" class="flex justify-center py-12">
      <Spinner />
    </div>

    <div
      v-else-if="!filteredTasks.length"
      class="rounded-2xl border border-dashed border-line bg-surface/50 px-6 py-12 text-center"
    >
      <p class="text-[14.5px] font-medium text-fg">还没有定时任务</p>
      <p class="mt-1.5 text-[13px] text-fg-muted">
        你可以点击右上角「新建定时任务」，或直接在聊天中告诉助理「每天早上 9 点帮我总结新闻」。
      </p>
      <div class="mt-4">
        <BaseButton size="sm" @click="openCreate">创建第一个定时任务</BaseButton>
      </div>
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="task in filteredTasks"
        :key="task.id"
        class="rounded-2xl border border-line/70 bg-surface p-4 transition-colors hover:border-line-strong"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-[14.5px] font-semibold text-fg">{{ task.name }}</h3>
              <BaseBadge :tone="statusMeta(task).tone">{{ statusMeta(task).label }}</BaseBadge>
              <span class="rounded-full bg-canvas px-2.5 py-0.5 text-[11.5px] font-medium text-fg-muted">
                {{ task.schedule_description }}
              </span>
              <button
                v-if="task.conversation_id"
                type="button"
                class="rounded-full bg-canvas px-2.5 py-0.5 text-[11.5px] font-medium text-accent hover:underline"
                @click="emit('open-conversation', task.conversation_id)"
              >
                {{ targetModeLabel(task) }} ↗
              </button>
              <span v-else class="rounded-full bg-canvas px-2.5 py-0.5 text-[11.5px] text-fg-faint">
                {{ targetModeLabel(task) }}
              </span>
            </div>

            <p class="mt-2 line-clamp-2 whitespace-pre-wrap text-[13px] leading-relaxed text-fg-muted">
              {{ task.prompt }}
            </p>

            <div class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-fg-faint">
              <span>下次执行：{{ task.enabled ? formatDateTime(task.next_run_at) : "已暂停" }}</span>
              <span>上次执行：{{ formatDateTime(task.last_run_at) }}</span>
              <span>累计运行：{{ task.run_count }} 次</span>
              <span>时区：{{ task.timezone }}</span>
            </div>
            <p v-if="task.last_error" class="mt-1.5 text-[12px] text-danger">
              最近异常：{{ task.last_error }}
            </p>
          </div>

          <div class="flex shrink-0 flex-wrap items-center gap-1.5">
            <BaseButton
              size="sm"
              variant="secondary"
              :loading="busyTaskId === task.id"
              @click="onRunNow(task)"
            >
              立即运行
            </BaseButton>
            <BaseButton
              size="sm"
              variant="secondary"
              :disabled="busyTaskId === task.id"
              @click="onToggleEnabled(task)"
            >
              {{ task.enabled ? "暂停" : "启用" }}
            </BaseButton>
            <BaseButton size="sm" variant="ghost" @click="onToggleHistory(task)">
              {{ expandedTaskId === task.id ? "收起历史" : "执行历史" }}
            </BaseButton>
            <BaseButton size="sm" variant="ghost" @click="openEdit(task)">编辑</BaseButton>
            <BaseButton size="sm" variant="ghost" class="text-danger hover:text-danger" @click="deleteTarget = task">
              删除
            </BaseButton>
          </div>
        </div>

        <!-- Expandable Run History -->
        <div v-if="expandedTaskId === task.id" class="mt-3.5 border-t border-line/70 pt-3">
          <div v-if="loadingRunsId === task.id" class="flex justify-center py-4">
            <Spinner />
          </div>
          <div
            v-else-if="!(schedules.runsByTask[task.id] || []).length"
            class="py-3 text-center text-[12.5px] text-fg-faint"
          >
            暂无执行记录
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="run in schedules.runsByTask[task.id]"
              :key="run.id"
              class="flex flex-wrap items-start justify-between gap-2 rounded-xl bg-canvas px-3 py-2.5 text-[12.5px]"
            >
              <div class="min-w-0 flex-1 space-y-0.5">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="rounded-full px-2 py-0.5 text-[11px] font-medium" :class="runStatusMeta(run).cls">
                    {{ runStatusMeta(run).label }}
                  </span>
                  <span class="text-fg-muted">{{ run.trigger_type === "manual" ? "手动触发" : "定时触发" }}</span>
                  <span class="text-fg-faint">{{ formatDateTime(run.started_at) }}</span>
                  <span v-if="run.tokens_used" class="text-fg-faint">{{ run.tokens_used }} tokens</span>
                </div>
                <p v-if="run.summary" class="line-clamp-2 text-fg-muted">{{ run.summary }}</p>
                <p v-if="run.error" class="text-danger">{{ run.error }}</p>
              </div>
              <button
                v-if="run.conversation_id"
                type="button"
                class="shrink-0 rounded-lg bg-surface px-2.5 py-1 text-[12px] font-medium text-accent hover:bg-hover"
                @click="emit('open-conversation', run.conversation_id)"
              >
                查看对话
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ScheduleEditorModal
      :open="editorOpen"
      :task="editingTask"
      :min-interval-minutes="schedules.quota.min_interval_minutes"
      @close="editorOpen = false"
    />

    <BaseModal :open="Boolean(deleteTarget)" title="删除定时任务" width="max-w-md" @close="deleteTarget = null">
      <p class="text-[13.5px] text-fg-muted">
        确定要删除定时任务「<span class="font-medium text-fg">{{ deleteTarget?.name }}</span>」吗？已有执行记录将一并清除，生成的历史对话消息会保留。
      </p>
      <div class="mt-5 flex justify-end gap-2">
        <BaseButton variant="secondary" @click="deleteTarget = null">取消</BaseButton>
        <BaseButton variant="danger" :loading="deleting" @click="confirmDelete">确认删除</BaseButton>
      </div>
    </BaseModal>
  </div>
</template>
