<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type {
  AdminActiveRun,
  AdminMonitor,
  OpsAlertEvent,
  OpsAlertRule,
  OpsAlertsResponse,
  OpsInspection,
} from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

const inspection = ref<OpsInspection | null>(null);
const alerts = ref<OpsAlertsResponse | null>(null);
const monitor = ref<AdminMonitor | null>(null);

const loading = ref(false);
const evaluating = ref(false);
const autoRefresh = ref(false);
const error = ref<string | null>(null);
const toast = ref<string | null>(null);

const ruleModalOpen = ref(false);
const ruleSaving = ref(false);
const ruleForm = ref({
  name: "",
  metric_key: "agent_error_rate_pct",
  operator: "gt" as "gt" | "gte" | "lt" | "lte" | "eq",
  threshold: "5",
  window_minutes: "15",
  cooldown_minutes: "30",
  severity: "warning" as "info" | "warning" | "critical",
  webhook_url: "",
});

const stopTarget = ref<AdminActiveRun | null>(null);
const stopLoading = ref(false);

let timer: number | null = null;

function showToast(msg: string) {
  toast.value = msg;
  window.setTimeout(() => {
    if (toast.value === msg) toast.value = null;
  }, 3500);
}

async function loadAll() {
  loading.value = true;
  error.value = null;
  try {
    const [insp, al, mon] = await Promise.all([
      api.get<OpsInspection>("/admin/ops/inspection"),
      api.get<OpsAlertsResponse>("/admin/ops/alerts"),
      api.get<AdminMonitor>("/admin/monitor"),
    ]);
    inspection.value = insp;
    alerts.value = al;
    monitor.value = mon;
  } catch (err) {
    error.value = readableError(err);
  } finally {
    loading.value = false;
  }
}

async function runEvaluate() {
  evaluating.value = true;
  try {
    const res = await api.post<{ evaluated: number; triggered: number }>("/admin/ops/alerts/evaluate", {});
    showToast(`巡检完成：评估 ${res.evaluated} 条规则，新触发 ${res.triggered} 条告警`);
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  } finally {
    evaluating.value = false;
  }
}

async function createRule() {
  if (!ruleForm.value.name.trim()) return;
  ruleSaving.value = true;
  try {
    await api.post("/admin/ops/alerts/rules", {
      ...ruleForm.value,
      threshold: Number(ruleForm.value.threshold),
      window_minutes: Number(ruleForm.value.window_minutes),
      cooldown_minutes: Number(ruleForm.value.cooldown_minutes),
      webhook_url: ruleForm.value.webhook_url.trim() || null,
    });
    ruleModalOpen.value = false;
    ruleForm.value.name = "";
    ruleForm.value.webhook_url = "";
    showToast("告警规则已创建");
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  } finally {
    ruleSaving.value = false;
  }
}

async function toggleRule(rule: OpsAlertRule) {
  try {
    await api.patch(`/admin/ops/alerts/rules/${rule.id}`, { enabled: !rule.enabled });
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  }
}

async function testWebhook(rule: OpsAlertRule) {
  try {
    const res = await api.post<{ ok: boolean; webhook_status: string }>(
      `/admin/ops/alerts/rules/${rule.id}/test`,
      {}
    );
    showToast(res.ok ? `Webhook 测试成功 (${res.webhook_status})` : `Webhook 返回 ${res.webhook_status}`);
  } catch (err) {
    error.value = readableError(err);
  }
}

async function deleteRule(rule: OpsAlertRule) {
  try {
    await api.delete(`/admin/ops/alerts/rules/${rule.id}`);
    showToast("已删除规则");
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  }
}

async function ackEvent(ev: OpsAlertEvent) {
  try {
    await api.post(`/admin/ops/alerts/${ev.id}/ack`, {});
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  }
}

async function confirmStopRun() {
  if (!stopTarget.value) return;
  stopLoading.value = true;
  try {
    await api.post(`/admin/conversations/${stopTarget.value.conversation_id}/stop`, {});
    stopTarget.value = null;
    showToast("已强制终止任务");
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  } finally {
    stopLoading.value = false;
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value;
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
  if (autoRefresh.value) {
    timer = window.setInterval(() => {
      void loadAll();
    }, 15000);
  }
}

const metricOptions = computed(() => {
  const map = inspection.value?.supported_metrics || alerts.value?.supported_metrics || {};
  return Object.entries(map).map(([key, meta]) => ({ key, label: meta.label, unit: meta.unit }));
});

function toneForSeverity(sev: string): "red" | "amber" | "gray" {
  if (sev === "critical") return "red";
  if (sev === "warning") return "amber";
  return "gray";
}

onMounted(() => {
  void loadAll();
});

onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight text-fg">运维监控看板</h1>
        <p class="mt-0.5 text-[13px] text-fg-muted">
          数据库、Redis、ARQ 队列、Agent 节点实时巡检与阈值告警中心
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <BaseButton variant="secondary" size="sm" @click="toggleAutoRefresh">
          <span
            class="h-2 w-2 rounded-full"
            :class="autoRefresh ? 'bg-success animate-pulse' : 'bg-fg-faint'"
          />
          {{ autoRefresh ? "自动刷新中 (15s)" : "自动刷新" }}
        </BaseButton>
        <BaseButton variant="secondary" size="sm" :loading="evaluating" @click="runEvaluate">
          <Icon name="activity" :size="14" />
          立即巡检评估
        </BaseButton>
        <BaseButton variant="secondary" size="sm" :loading="loading" @click="loadAll">
          <Icon name="refresh" :size="14" />
          刷新
        </BaseButton>
      </div>
    </div>

    <div v-if="toast" class="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] text-fg">
      {{ toast }}
    </div>
    <div v-if="error" class="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-[13px] text-danger">
      {{ error }}
    </div>

    <!-- 实时运行水位 KPI -->
    <div v-if="inspection" class="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">近 15m 运行 / 失败率</p>
        <p class="mt-1.5 text-xl font-semibold text-fg">
          {{ inspection.runtime.runs_15m }}
          <span class="text-[13px] font-normal" :class="inspection.runtime.error_rate_15m_pct > 5 ? 'text-danger' : 'text-fg-muted'">
            ({{ inspection.runtime.error_rate_15m_pct }}%)
          </span>
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">近 15m P95 延迟</p>
        <p class="mt-1.5 text-xl font-semibold text-fg">{{ inspection.runtime.p95_latency_15m_ms }} ms</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">ARQ 队列积压 / 进行中</p>
        <p class="mt-1.5 text-xl font-semibold text-fg">
          {{ inspection.redis.arq_queue_depth ?? 0 }}
          <span class="text-[13px] font-normal text-fg-muted">/ {{ inspection.redis.arq_in_progress ?? 0 }}</span>
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">活跃任务 / 卡死预警</p>
        <p class="mt-1.5 text-xl font-semibold text-fg">
          {{ inspection.runtime.active_runs }}
          <span class="text-[13px] font-normal" :class="inspection.runtime.stuck_runs > 0 ? 'text-danger' : 'text-fg-muted'">
            / {{ inspection.runtime.stuck_runs }} 卡死
          </span>
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">未确认告警</p>
        <p class="mt-1.5 text-xl font-semibold" :class="inspection.runtime.firing_alerts > 0 ? 'text-danger' : 'text-fg'">
          {{ inspection.runtime.firing_alerts }}
        </p>
      </div>
    </div>

    <!-- SLO 错误预算与 Z-Score 异常检测 -->
    <div v-if="inspection?.slo" class="grid gap-4 lg:grid-cols-2">
      <div class="rounded-2xl border border-line bg-surface p-5">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h2 class="text-[14px] font-semibold text-fg">SLO 与错误预算燃烧率 (Error Budget)</h2>
            <p class="text-[12px] text-fg-muted">
              目标可用性 ≥ {{ inspection.slo.availability_target_pct }}% · P95 ≤ {{ inspection.slo.p95_target_ms }}ms
            </p>
          </div>
          <BaseBadge
            :tone="inspection.slo.status === 'critical' ? 'red' : inspection.slo.status === 'warning' ? 'amber' : 'green'"
          >
            {{ inspection.slo.status === "critical" ? "预算告急" : inspection.slo.status === "warning" ? "需关注" : "健康" }}
          </BaseBadge>
        </div>

        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div class="rounded-xl border border-line bg-canvas p-3">
            <p class="text-[11px] text-fg-faint">7d 剩余预算</p>
            <p
              class="mt-1 text-lg font-semibold"
              :class="inspection.slo.error_budget_remaining_pct <= 20 ? 'text-danger' : 'text-fg'"
            >
              {{ inspection.slo.error_budget_remaining_pct }}%
            </p>
          </div>
          <div class="rounded-xl border border-line bg-canvas p-3">
            <p class="text-[11px] text-fg-faint">1h / 24h 燃烧率</p>
            <p class="mt-1 text-lg font-semibold text-fg">
              {{ inspection.slo.burn_rate_1h }}x
              <span class="text-[12px] font-normal text-fg-muted">/ {{ inspection.slo.burn_rate_24h }}x</span>
            </p>
          </div>
          <div class="rounded-xl border border-line bg-canvas p-3">
            <p class="text-[11px] text-fg-faint">24h 成功率 / P95</p>
            <p class="mt-1 text-lg font-semibold text-fg">
              {{ inspection.slo.actual_success_rate_24h_pct }}%
            </p>
            <p class="text-[10.5px] text-fg-faint">P95: {{ inspection.slo.actual_p95_24h_ms }} ms</p>
          </div>
          <div class="rounded-xl border border-line bg-canvas p-3">
            <p class="text-[11px] text-fg-faint">1h / 24h 模型开销</p>
            <p class="mt-1 text-lg font-semibold text-fg">${{ inspection.slo.cost_1h_usd.toFixed(3) }}</p>
            <p class="text-[10.5px] text-fg-faint">24h: ${{ inspection.slo.cost_24h_usd.toFixed(3) }}</p>
          </div>
        </div>
      </div>

      <div class="rounded-2xl border border-line bg-surface p-5">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h2 class="text-[14px] font-semibold text-fg">Z-Score 统计异常检测 (1h vs 7d 基线)</h2>
            <p class="text-[12px] text-fg-muted">Z-Score ≥ 2.5 判定为统计离群突刺</p>
          </div>
        </div>
        <div v-if="!inspection.anomalies?.length" class="py-6 text-center text-[13px] text-fg-faint">
          暂无足够基线样本
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="anom in inspection.anomalies"
            :key="anom.metric"
            class="flex items-center justify-between rounded-xl border border-line bg-canvas px-3 py-2 text-[12.5px]"
          >
            <div>
              <span class="font-medium text-fg">{{ anom.label }}</span>
              <span class="ml-2 text-[11px] text-fg-faint">
                基线 {{ anom.baseline_mean }} ± {{ anom.baseline_std }} ({{ anom.sample_hours }}h)
              </span>
            </div>
            <div class="flex items-center gap-2">
              <span class="font-mono text-fg">{{ anom.current }} {{ anom.unit }}</span>
              <BaseBadge :tone="anom.is_anomaly ? 'red' : Math.abs(anom.z_score) >= 1.5 ? 'amber' : 'gray'">
                z={{ anom.z_score }}
              </BaseBadge>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 基础设施资源卡片 -->
    <div v-if="inspection" class="grid gap-4 lg:grid-cols-3">
      <!-- Postgres -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <div class="flex items-center justify-between">
          <h2 class="text-[14px] font-semibold text-fg">PostgreSQL</h2>
          <BaseBadge :tone="inspection.postgres.ok ? 'green' : 'red'">
            {{ inspection.postgres.ok ? `正常 · ${inspection.postgres.latency_ms ?? '-'}ms` : "异常" }}
          </BaseBadge>
        </div>
        <div class="mt-4 space-y-2.5 text-[12.5px]">
          <div class="flex justify-between text-fg-muted">
            <span>连接数 ({{ inspection.postgres.active_connections ?? 0 }} 活跃)</span>
            <span class="font-medium text-fg">
              {{ inspection.postgres.total_connections ?? 0 }} / {{ inspection.postgres.max_connections ?? 0 }}
              ({{ inspection.postgres.connection_pct ?? 0 }}%)
            </span>
          </div>
          <div class="h-1.5 overflow-hidden rounded-full bg-hover">
            <div
              class="h-full rounded-full bg-accent transition-all"
              :style="{ width: `${Math.min(100, inspection.postgres.connection_pct ?? 0)}%` }"
            />
          </div>
          <div class="flex justify-between text-fg-muted">
            <span>库容量 / pgvector</span>
            <span class="text-fg">
              {{ inspection.postgres.database_size_mb ?? 0 }} MB ·
              {{ inspection.postgres.pgvector ? "pgvector 已启用" : "未启用" }}
            </span>
          </div>
        </div>
      </div>

      <!-- Redis -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <div class="flex items-center justify-between">
          <h2 class="text-[14px] font-semibold text-fg">Redis & ARQ</h2>
          <BaseBadge :tone="inspection.redis.ok ? 'green' : 'red'">
            {{ inspection.redis.ok ? `正常 · ${inspection.redis.latency_ms ?? '-'}ms` : "异常" }}
          </BaseBadge>
        </div>
        <div class="mt-4 space-y-2.5 text-[12.5px]">
          <div class="flex justify-between text-fg-muted">
            <span>内存水位</span>
            <span class="font-medium text-fg">
              {{ inspection.redis.used_memory_mb ?? 0 }} / {{ inspection.redis.maxmemory_mb || "∞" }} MB
              ({{ inspection.redis.memory_pct ?? 0 }}%)
            </span>
          </div>
          <div class="h-1.5 overflow-hidden rounded-full bg-hover">
            <div
              class="h-full rounded-full transition-all"
              :class="(inspection.redis.memory_pct ?? 0) > 80 ? 'bg-danger' : 'bg-[#7C6BF0]'"
              :style="{ width: `${Math.min(100, inspection.redis.memory_pct ?? 0)}%` }"
            />
          </div>
          <div class="flex justify-between text-fg-muted">
            <span>缓存命中率 / 客户端</span>
            <span class="text-fg">
              {{ inspection.redis.hit_rate_pct ?? 100 }}% · {{ inspection.redis.connected_clients ?? 0 }} 连接
            </span>
          </div>
        </div>
      </div>

      <!-- Agent & Worker -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <div class="flex items-center justify-between">
          <h2 class="text-[14px] font-semibold text-fg">LangGraph Agent & Worker</h2>
          <BaseBadge :tone="inspection.agent.ok && inspection.agent.worker_ok ? 'green' : 'red'">
            {{ inspection.agent.ok ? `在线 · ${inspection.agent.latency_ms ?? '-'}ms` : "离线" }}
          </BaseBadge>
        </div>
        <div class="mt-4 space-y-2.5 text-[12.5px]">
          <div class="flex justify-between text-fg-muted">
            <span>Agent API 状态</span>
            <span class="font-medium text-fg">{{ inspection.agent.ok ? "Ready" : "Unavailable" }}</span>
          </div>
          <div class="flex justify-between text-fg-muted">
            <span>ARQ Worker 连通</span>
            <span class="font-medium text-fg">{{ inspection.agent.worker_ok ? "在线" : "离线" }}</span>
          </div>
          <div class="flex justify-between text-fg-muted">
            <span>沙箱模式 / 并发上限</span>
            <span class="text-fg">
              {{ inspection.agent.sandbox_mode ?? "disabled" }} · 上限 {{ inspection.runtime.max_concurrent_runs }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 活跃任务队列 -->
    <div class="rounded-2xl border border-line bg-surface p-5">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-[14px] font-semibold text-fg">实时活跃任务 ({{ monitor?.active_runs.length ?? 0 }})</h2>
        <span class="text-[12px] text-fg-faint">超时阈值 {{ inspection?.runtime.run_max_seconds ?? 900 }}s</span>
      </div>
      <div v-if="!monitor?.active_runs.length" class="py-6 text-center text-[13px] text-fg-faint">
        当前无运行中的 Agent 任务
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-left text-[12.5px]">
          <thead>
            <tr class="border-b border-line text-fg-muted">
              <th class="pb-2 font-medium">用户</th>
              <th class="pb-2 font-medium">会话</th>
              <th class="pb-2 font-medium">状态</th>
              <th class="pb-2 font-medium">耗时</th>
              <th class="pb-2 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="run in monitor.active_runs" :key="run.conversation_id">
              <td class="py-2.5 text-fg">{{ run.user_email }}</td>
              <td class="py-2.5 text-fg-muted">{{ run.title }}</td>
              <td class="py-2.5">
                <BaseBadge :tone="run.is_stalled ? 'red' : 'amber'">
                  {{ run.is_stalled ? "疑似卡死" : run.active_run_status }}
                </BaseBadge>
              </td>
              <td class="py-2.5 font-mono text-fg-muted">{{ run.duration_seconds }}s</td>
              <td class="py-2.5 text-right">
                <BaseButton variant="danger" size="sm" @click="stopTarget = run">强制终止</BaseButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 告警规则与告警事件 -->
    <div class="grid gap-4 lg:grid-cols-2">
      <!-- 告警事件 -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <h2 class="mb-3 text-[14px] font-semibold text-fg">最近告警事件</h2>
        <div v-if="!alerts?.events.length" class="py-8 text-center text-[13px] text-fg-faint">
          暂无告警事件记录
        </div>
        <div v-else class="space-y-2.5">
          <div
            v-for="ev in alerts.events"
            :key="ev.id"
            class="flex items-start justify-between gap-3 rounded-xl border border-line bg-canvas p-3"
          >
            <div class="min-w-0 space-y-1">
              <div class="flex items-center gap-2">
                <BaseBadge :tone="toneForSeverity(ev.severity)">{{ ev.severity }}</BaseBadge>
                <BaseBadge :tone="ev.status === 'firing' ? 'red' : 'gray'">{{ ev.status }}</BaseBadge>
                <span class="truncate text-[13px] font-medium text-fg">{{ ev.rule_name }}</span>
              </div>
              <p class="text-[12px] text-fg-muted">{{ ev.message }}</p>
              <p class="text-[11px] text-fg-faint">
                {{ new Date(ev.created_at).toLocaleString("zh-CN") }}
                <span v-if="ev.webhook_status"> · Webhook: {{ ev.webhook_status }}</span>
              </p>
            </div>
            <BaseButton
              v-if="ev.status === 'firing'"
              variant="secondary"
              size="sm"
              @click="ackEvent(ev)"
            >
              确认
            </BaseButton>
          </div>
        </div>
      </div>

      <!-- 告警规则 -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-[14px] font-semibold text-fg">告警规则配置</h2>
          <BaseButton size="sm" @click="ruleModalOpen = true">
            <Icon name="plus" :size="14" />
            新建规则
          </BaseButton>
        </div>
        <div v-if="!alerts?.rules.length" class="py-8 text-center text-[13px] text-fg-faint">
          尚未配置告警规则，点击右上角创建
        </div>
        <div v-else class="space-y-2.5">
          <div
            v-for="rule in alerts.rules"
            :key="rule.id"
            class="rounded-xl border border-line bg-canvas p-3"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <BaseBadge :tone="toneForSeverity(rule.severity)">{{ rule.severity }}</BaseBadge>
                <span class="text-[13px] font-medium text-fg">{{ rule.name }}</span>
              </div>
              <div class="flex items-center gap-1.5">
                <BaseButton variant="secondary" size="sm" @click="toggleRule(rule)">
                  {{ rule.enabled ? "已启用" : "已停用" }}
                </BaseButton>
                <BaseButton v-if="rule.webhook_url" variant="secondary" size="sm" @click="testWebhook(rule)">
                  测试
                </BaseButton>
                <BaseButton variant="danger" size="sm" @click="deleteRule(rule)">删除</BaseButton>
              </div>
            </div>
            <p class="mt-1.5 text-[12px] text-fg-muted">
              {{ rule.metric_label }} {{ rule.operator }} {{ rule.threshold }} · 窗口 {{ rule.window_minutes }}m · 冷却 {{ rule.cooldown_minutes }}m
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建告警规则弹窗 -->
    <BaseModal :open="ruleModalOpen" title="新建运维告警规则" @close="ruleModalOpen = false">
      <div class="space-y-3">
        <BaseInput v-model="ruleForm.name" label="规则名称" placeholder="例如：高失败率告警" />
        <div>
          <label class="mb-1 block text-[12px] font-medium text-fg-muted">监控指标</label>
          <select
            v-model="ruleForm.metric_key"
            class="h-9 w-full rounded-lg border border-line bg-canvas px-3 text-[13px] text-fg"
          >
            <option v-for="m in metricOptions" :key="m.key" :value="m.key">
              {{ m.label }} ({{ m.key }})
            </option>
          </select>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <div>
            <label class="mb-1 block text-[12px] font-medium text-fg-muted">比较符</label>
            <select v-model="ruleForm.operator" class="h-9 w-full rounded-lg border border-line bg-canvas px-2 text-[13px] text-fg">
              <option value="gt">&gt;</option>
              <option value="gte">&gt;=</option>
              <option value="lt">&lt;</option>
              <option value="lte">&lt;=</option>
              <option value="eq">=</option>
            </select>
          </div>
          <BaseInput v-model="ruleForm.threshold" label="阈值" type="number" />
          <div>
            <label class="mb-1 block text-[12px] font-medium text-fg-muted">级别</label>
            <select v-model="ruleForm.severity" class="h-9 w-full rounded-lg border border-line bg-canvas px-2 text-[13px] text-fg">
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <BaseInput v-model="ruleForm.window_minutes" label="统计窗口 (分钟)" type="number" />
          <BaseInput v-model="ruleForm.cooldown_minutes" label="冷却期 (分钟)" type="number" />
        </div>
        <BaseInput
          v-model="ruleForm.webhook_url"
          label="Webhook URL (飞书/钉钉/Slack，可选)"
          placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
        />
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="ruleModalOpen = false">取消</BaseButton>
        <BaseButton :loading="ruleSaving" @click="createRule">保存规则</BaseButton>
      </template>
    </BaseModal>

    <!-- 强制终止确认弹窗 -->
    <BaseModal :open="Boolean(stopTarget)" title="确认强制终止任务" @close="stopTarget = null">
      <p class="text-[13px] text-fg-muted">
        确定要终止用户 <strong class="text-fg">{{ stopTarget?.user_email }}</strong> 的当前运行任务吗？
      </p>
      <template #footer>
        <BaseButton variant="secondary" @click="stopTarget = null">取消</BaseButton>
        <BaseButton variant="danger" :loading="stopLoading" @click="confirmStopRun">确认终止</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
