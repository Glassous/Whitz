import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api/client";
import type {
  ScheduleModelRoute,
  ScheduleOverview,
  SchedulePreviewResult,
  ScheduleQuota,
  ScheduleTargetMode,
  ScheduleType,
  ScheduledTask,
  ScheduledTaskPendingItem,
  ScheduledTaskRun,
} from "../types";

export interface ScheduleFormPayload {
  name: string;
  prompt: string;
  schedule_type: ScheduleType;
  schedule_config: Record<string, any>;
  timezone?: string;
  target_mode: ScheduleTargetMode;
  conversation_id?: string | null;
  model_route: ScheduleModelRoute;
  skill_names: string[];
  enabled?: boolean;
}

export const useSchedulesStore = defineStore("schedules", () => {
  const tasks = ref<ScheduledTask[]>([]);
  const pending = ref<ScheduledTaskPendingItem[]>([]);
  const quota = ref<ScheduleQuota>({
    tier: "free",
    max_active_tasks: 3,
    active_count: 0,
    min_interval_minutes: 60,
  });
  const loading = ref(false);
  const runsByTask = ref<Record<string, ScheduledTaskRun[]>>({});

  function recomputeActiveCount() {
    quota.value = {
      ...quota.value,
      active_count: tasks.value.filter((t) => t.enabled).length,
    };
  }

  async function fetchAll() {
    loading.value = true;
    try {
      const data = await api.get<ScheduleOverview>("/schedules");
      tasks.value = Array.isArray(data?.tasks) ? data.tasks : [];
      pending.value = Array.isArray(data?.pending) ? data.pending : [];
      if (data?.quota) quota.value = data.quota;
    } finally {
      loading.value = false;
    }
  }

  async function fetchDetail(taskId: string): Promise<ScheduledTask> {
    const detail = await api.get<ScheduledTask>(`/schedules/${taskId}`);
    const idx = tasks.value.findIndex((t) => t.id === taskId);
    if (idx >= 0) {
      tasks.value[idx] = { ...tasks.value[idx], ...detail };
    }
    if (Array.isArray(detail.runs)) {
      runsByTask.value = { ...runsByTask.value, [taskId]: detail.runs };
    }
    return detail;
  }

  async function preview(payload: {
    schedule_type: ScheduleType;
    schedule_config: Record<string, any>;
    timezone?: string;
    count?: number;
  }): Promise<SchedulePreviewResult> {
    return api.post<SchedulePreviewResult>("/schedules/preview", payload);
  }

  async function createTask(payload: ScheduleFormPayload): Promise<ScheduledTask> {
    const created = await api.post<ScheduledTask>("/schedules", payload);
    upsertLocalTask(created);
    return created;
  }

  async function updateTask(taskId: string, payload: Partial<ScheduleFormPayload>): Promise<ScheduledTask> {
    const updated = await api.patch<ScheduledTask>(`/schedules/${taskId}`, payload);
    upsertLocalTask(updated);
    return updated;
  }

  async function deleteTask(taskId: string): Promise<void> {
    await api.delete(`/schedules/${taskId}`);
    removeLocalTask(taskId);
  }

  async function runNow(taskId: string): Promise<ScheduledTaskRun> {
    const run = await api.post<ScheduledTaskRun>(`/schedules/${taskId}/run-now`, {});
    upsertLocalRun(taskId, run);
    return run;
  }

  async function resolvePending(proposalId: string, action: "approve" | "reject"): Promise<void> {
    const res = await api.post<{ status: string; task?: ScheduledTask | null }>(
      `/schedules/pending/${proposalId}`,
      { action },
    );
    pending.value = pending.value.filter((p) => p.id !== proposalId);
    if (res?.task) {
      upsertLocalTask(res.task);
    } else if (action === "approve") {
      await fetchAll();
    }
  }

  function upsertLocalTask(task: ScheduledTask) {
    const idx = tasks.value.findIndex((t) => t.id === task.id);
    if (idx >= 0) {
      const next = [...tasks.value];
      next[idx] = { ...next[idx], ...task };
      tasks.value = next;
    } else {
      tasks.value = [task, ...tasks.value];
    }
    recomputeActiveCount();
  }

  function removeLocalTask(taskId: string) {
    tasks.value = tasks.value.filter((t) => t.id !== taskId);
    const { [taskId]: _, ...rest } = runsByTask.value;
    runsByTask.value = rest;
    recomputeActiveCount();
  }

  function upsertLocalRun(taskId: string, run: ScheduledTaskRun) {
    const existing = runsByTask.value[taskId] ?? [];
    const idx = existing.findIndex((r) => r.id === run.id);
    let next: ScheduledTaskRun[];
    if (idx >= 0) {
      next = [...existing];
      next[idx] = run;
    } else {
      next = [run, ...existing].slice(0, 30);
    }
    runsByTask.value = { ...runsByTask.value, [taskId]: next };
  }

  return {
    tasks,
    pending,
    quota,
    loading,
    runsByTask,
    fetchAll,
    fetchDetail,
    preview,
    createTask,
    updateTask,
    deleteTask,
    runNow,
    resolvePending,
    upsertLocalTask,
    removeLocalTask,
    upsertLocalRun,
  };
});
