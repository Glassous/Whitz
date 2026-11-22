<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type { HttpToolsDashboard, SchedulesDashboard, WebSearchDashboard } from "../types";
import DailySuccessChart, { type DailyChartPoint } from "../components/DailySuccessChart.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import Icon from "../components/ui/Icon.vue";

type DayWindow = 7 | 14 | 30;
type SectionTab = "all" | "schedules" | "http" | "search";

const days = ref<DayWindow>(14);
const activeTab = ref<SectionTab>("all");
const schedules = ref<SchedulesDashboard | null>(null);
const httpTools = ref<HttpToolsDashboard | null>(null);
const webSearch = ref<WebSearchDashboard | null>(null);

const loading = ref(false);
const exporting = ref(false);
const autoRefresh = ref(false);
const error = ref<string | null>(null);
const toast = ref<string | null>(null);

let refreshTimer: number | null = null;
const numberFormat = new Intl.NumberFormat("zh-CN");

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
    const [schedRes, httpRes, searchRes] = await Promise.all([
      api.get<SchedulesDashboard>(`/admin/dashboards/schedules?days=${days.value}`),
      api.get<HttpToolsDashboard>(`/admin/dashboards/http-tools?days=${days.value}`),
      api.get<WebSearchDashboard>(`/admin/dashboards/web-search?days=${days.value}`),
    ]);
    schedules.value = schedRes;
    httpTools.value = httpRes;
    webSearch.value = searchRes;
  } catch (err) {
    error.value = readableError(err);
  } finally {
    loading.value = false;
  }
}

function selectDays(d: DayWindow) {
  if (days.value === d) return;
  days.value = d;
  void loadAll();
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value;
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (autoRefresh.value) {
    refreshTimer = window.setInterval(() => {
      void loadAll();
    }, 30000);
  }
}

async function exportCsv() {
  exporting.value = true;
  try {
    await api.download(
      `/admin/dashboards/export?days=${days.value}&section=${activeTab.value}`,
      `whitz-automation-${activeTab.value}-${days.value}d.csv`,
    );
    showToast("看板日报 CSV 已导出");
  } catch (err) {
    error.value = readableError(err);
  } finally {
    exporting.value = false;
  }
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Number(v).toFixed(1)}%`;
}

function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1000) return `${(v / 1000).toFixed(2)}s`;
  return `${Math.round(v)} ms`;
}

function fmtBytes(bytes: number | null | undefined): string {
  const b = Number(bytes || 0);
  if (b >= 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(2)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

function fmtTime(iso: string | null | undefined): string {
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

function rateTone(rate: number | null | undefined): "green" | "amber" | "red" | "gray" {
  if (rate === null || rate === undefined) return "gray";
  if (rate >= 95) return "green";
  if (rate >= 80) return "amber";
  return "red";
}

function rateTextClass(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "text-fg-muted";
  if (rate >= 95) return "text-success";
  if (rate >= 80) return "text-warning";
  return "text-danger";
}

const scheduleDailyPoints = computed<DailyChartPoint[]>(() => {
  return (schedules.value?.daily ?? []).map((r) => ({
    day: r.day,
    total: r.total,
    succeeded: r.completed,
    failed: r.failed,
    success_rate_pct: r.success_rate_pct,
    extraLabel: `Tokens ${numberFormat.format(r.tokens)}`,
  }));
});

const httpDailyPoints = computed<DailyChartPoint[]>(() => {
  return (httpTools.value?.http_request.daily ?? []).map((r) => ({
    day: r.day,
    total: r.total,
    succeeded: r.succeeded,
    failed: r.failed,
    success_rate_pct: r.success_rate_pct,
    extraLabel: r.avg_duration_ms !== null ? `均耗 ${fmtMs(r.avg_duration_ms)}` : undefined,
  }));
});

const searchDailyPoints = computed<DailyChartPoint[]>(() => {
  return (webSearch.value?.daily ?? []).map((r) => ({
    day: r.day,
    total: r.total,
    succeeded: r.succeeded,
    failed: r.failed,
    success_rate_pct: r.success_rate_pct,
    extraLabel: `有结果 ${r.with_results} · 降级 ${r.fallback_count}`,
  }));
});

const TRIGGER_LABELS: Record<string, string> = {
  scheduled: "定时自动调度",
  manual: "手动立即执行",
};

const SCHEDULE_TYPE_LABELS: Record<string, string> = {
  daily: "每天",
  interval: "固定间隔",
  weekly: "每周",
  monthly: "每月",
  cron: "Cron",
  once: "单次",
};

const TARGET_MODE_LABELS: Record<string, string> = {
  dedicated: "专属旁聊",
  main: "主聊天",
  conversation: "指定旁聊",
};

const STATUS_BUCKET_LABELS: Record<string, string> = {
  "2xx": "2xx 成功",
  "3xx": "3xx 重定向",
  "4xx": "4xx 客户端错误",
  "5xx": "5xx 服务端错误",
  network_error: "网络/超时/SSRF 拦截",
};

const PROVIDER_LABELS: Record<string, string> = {
  bocha: "博查 AI",
  tavily: "Tavily",
  duckduckgo: "DuckDuckGo (兜底/免费)",
  http: "直连 HTTP",
  none: "全部引擎失败",
  unknown: "未知",
};

onMounted(() => {
  void loadAll();
});

onBeforeUnmount(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
});
</script>

<template>
  <div class="space-y-6">
    <!-- 顶部栏 -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight text-fg">定时任务与网络工具看板</h1>
        <p class="mt-0.5 text-[13px] text-fg-muted">
          定时任务执行成功率与准时率、Curl / HTTP 请求状态码与沙盒执行分析、联网搜索次数与引擎命中率监控
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <div class="inline-flex rounded-xl border border-line bg-surface p-0.5">
          <button
            v-for="d in ([7, 14, 30] as const)"
            :key="d"
            class="rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors"
            :class="days === d ? 'bg-active text-fg' : 'text-fg-muted hover:text-fg'"
            @click="selectDays(d)"
          >
            {{ d }}天
          </button>
        </div>
        <BaseButton variant="secondary" size="sm" @click="toggleAutoRefresh">
          <span
            class="h-2 w-2 rounded-full"
            :class="autoRefresh ? 'bg-success animate-pulse' : 'bg-fg-faint'"
          />
          {{ autoRefresh ? "自动刷新 (30s)" : "自动刷新" }}
        </BaseButton>
        <BaseButton variant="secondary" size="sm" :loading="exporting" @click="exportCsv">
          导出 CSV
        </BaseButton>
        <BaseButton variant="secondary" size="sm" :loading="loading" @click="loadAll">
          <Icon name="refresh" :size="14" />
          刷新
        </BaseButton>
      </div>
    </div>

    <!-- 板块切换 Tabs -->
    <div class="flex flex-wrap items-center gap-1.5 rounded-2xl border border-line bg-surface p-1.5">
      <button
        v-for="tab in ([
          { key: 'all', label: '全部看板', icon: 'overview' },
          { key: 'schedules', label: '定时任务看板', icon: 'clock' },
          { key: 'http', label: 'Curl / HTTP 与沙盒', icon: 'terminal' },
          { key: 'search', label: '联网搜索看板', icon: 'globe' },
        ] as const)"
        :key="tab.key"
        type="button"
        class="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-[12.5px] font-medium transition-colors"
        :class="activeTab === tab.key ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
        @click="activeTab = tab.key"
      >
        <Icon :name="tab.icon" :size="14" />
        {{ tab.label }}
      </button>
    </div>

    <div v-if="toast" class="rounded-xl border border-line bg-surface px-4 py-2.5 text-[13px] text-fg">
      {{ toast }}
    </div>
    <div v-if="error" class="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-[13px] text-danger">
      {{ error }}
    </div>

    <!-- ==================== 1. 定时任务看板 ==================== -->
    <section v-if="schedules && (activeTab === 'all' || activeTab === 'schedules')" class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Icon name="clock" :size="16" class="text-accent" />
          <h2 class="text-[15px] font-semibold text-fg">定时任务执行看板</h2>
        </div>
        <div class="flex flex-wrap items-center gap-2 text-[12px] text-fg-muted">
          <span>任务总数 {{ schedules.tasks_summary.total }}</span>
          <span>· 活跃 {{ schedules.tasks_summary.active }}</span>
          <span :class="schedules.tasks_summary.error > 0 ? 'text-danger font-medium' : ''">
            · 异常暂停 {{ schedules.tasks_summary.error }}
          </span>
          <span v-if="schedules.tasks_summary.pending_proposals > 0" class="text-warning">
            · 待审批提案 {{ schedules.tasks_summary.pending_proposals }}
          </span>
        </div>
      </div>

      <!-- 定时任务 KPI -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">窗口执行总次数</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ numberFormat.format(schedules.runs_summary.total) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            进行中 {{ schedules.runs_summary.in_progress }} · 取消 {{ schedules.runs_summary.cancelled }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">定时任务成功率</p>
          <p class="mt-1 text-xl font-semibold" :class="rateTextClass(schedules.runs_summary.success_rate_pct)">
            {{ fmtPct(schedules.runs_summary.success_rate_pct) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            成功 {{ schedules.runs_summary.completed }} / 失败 {{ schedules.runs_summary.failed }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">准时调度率 (≤60s)</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ fmtPct(schedules.runs_summary.on_time_rate_pct) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            平均延迟 {{ fmtMs(schedules.runs_summary.avg_dispatch_delay_ms) }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">平均 / P95 耗时</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ fmtMs(schedules.runs_summary.avg_duration_ms) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">P95: {{ fmtMs(schedules.runs_summary.p95_duration_ms) }}</p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">启用任务 / 异常暂停</p>
          <p class="mt-1 text-xl font-semibold text-fg">
            {{ schedules.tasks_summary.enabled }}
            <span class="text-[13px] font-normal" :class="schedules.tasks_summary.error > 0 ? 'text-danger' : 'text-fg-faint'">
              / {{ schedules.tasks_summary.error }} 异常
            </span>
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            已暂停 {{ schedules.tasks_summary.paused }} · 已完成 {{ schedules.tasks_summary.completed }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">定时任务 Token 消耗</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ numberFormat.format(schedules.runs_summary.total_tokens) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">近 {{ schedules.window_days }} 天累计</p>
        </div>
      </div>

      <!-- 每日趋势 + 触发/类型分布 -->
      <div class="grid gap-4 lg:grid-cols-3">
        <div class="lg:col-span-2">
          <DailySuccessChart
            title="定时任务每日执行趋势与成功率"
            subtitle="统计窗口内每日调度执行次数、失败数及成功率变化"
            :rows="scheduleDailyPoints"
          />
        </div>

        <div class="space-y-4 rounded-2xl border border-line bg-surface p-5">
          <div>
            <h3 class="mb-2.5 text-[14px] font-semibold text-fg">触发方式对比</h3>
            <div class="space-y-2.5">
              <div
                v-for="tr in schedules.by_trigger"
                :key="tr.trigger_type"
                class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
              >
                <div class="flex items-center justify-between">
                  <span class="font-medium text-fg">{{ TRIGGER_LABELS[tr.trigger_type] || tr.trigger_type }}</span>
                  <BaseBadge :tone="rateTone(tr.success_rate_pct)">{{ fmtPct(tr.success_rate_pct) }}</BaseBadge>
                </div>
                <p class="mt-1 text-fg-muted">
                  总 {{ tr.total }} 次 · 成功 {{ tr.completed }} · 失败 {{ tr.failed }}
                </p>
              </div>
            </div>
          </div>

          <div class="border-t border-line pt-3">
            <h3 class="mb-2 text-[13px] font-semibold text-fg">任务类型与投递模式</h3>
            <div class="flex flex-wrap gap-1.5">
              <BaseBadge v-for="st in schedules.tasks_summary.by_schedule_type" :key="st.type" tone="gray">
                {{ SCHEDULE_TYPE_LABELS[st.type] || st.type }}: {{ st.count }}
              </BaseBadge>
              <BaseBadge v-for="tm in schedules.tasks_summary.by_target_mode" :key="tm.mode" tone="blue">
                {{ TARGET_MODE_LABELS[tm.mode] || tm.mode }}: {{ tm.count }}
              </BaseBadge>
            </div>
          </div>
        </div>
      </div>

      <!-- 任务排行与最近失败 -->
      <div class="grid gap-4 lg:grid-cols-3">
        <div class="rounded-2xl border border-line bg-surface p-5 lg:col-span-2">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">定时任务执行健康度排行</h3>
          <div v-if="!schedules.top_tasks.length" class="py-8 text-center text-[13px] text-fg-faint">
            暂无定时任务数据
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-[12px]">
              <thead>
                <tr class="border-b border-line text-fg-muted">
                  <th class="pb-2 font-medium">任务名称</th>
                  <th class="pb-2 font-medium">调度规则</th>
                  <th class="pb-2 font-medium">状态</th>
                  <th class="pb-2 text-right font-medium">执行 / 失败</th>
                  <th class="pb-2 text-right font-medium">成功率</th>
                  <th class="pb-2 text-right font-medium">均耗</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="task in schedules.top_tasks.slice(0, 12)" :key="task.task_id">
                  <td class="py-2 pr-2">
                    <p class="max-w-[200px] truncate font-medium text-fg">{{ task.name }}</p>
                    <p class="max-w-[200px] truncate text-[11px] text-fg-faint">{{ task.user_email }}</p>
                  </td>
                  <td class="py-2 pr-2 text-fg-muted">{{ task.schedule_description }}</td>
                  <td class="py-2 pr-2">
                    <BaseBadge
                      :tone="task.status === 'error' ? 'red' : task.enabled ? 'green' : 'gray'"
                    >
                      {{ task.status === 'error' ? `异常(${task.consecutive_failures})` : task.enabled ? '启用' : task.status }}
                    </BaseBadge>
                  </td>
                  <td class="py-2 text-right text-fg-muted">
                    {{ task.runs }} / <span :class="task.failed > 0 ? 'text-danger font-medium' : ''">{{ task.failed }}</span>
                  </td>
                  <td class="py-2 text-right font-medium" :class="rateTextClass(task.success_rate_pct)">
                    {{ fmtPct(task.success_rate_pct) }}
                  </td>
                  <td class="py-2 text-right text-fg-muted">{{ fmtMs(task.avg_duration_ms) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">最近定时任务失败</h3>
          <div v-if="!schedules.recent_failures.length" class="py-8 text-center text-[13px] text-fg-faint">
            统计窗口内无失败记录
          </div>
          <div v-else class="max-h-72 space-y-2 overflow-y-auto pr-1">
            <div
              v-for="fail in schedules.recent_failures"
              :key="fail.id"
              class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="truncate font-medium text-fg">{{ fail.task_name }}</span>
                <BaseBadge tone="red">{{ fail.trigger_type }}</BaseBadge>
              </div>
              <p class="mt-1 line-clamp-2 text-danger">{{ fail.error }}</p>
              <p class="mt-1 text-[11px] text-fg-faint">
                {{ fail.user_email }} · {{ fmtTime(fail.started_at) }} · {{ fmtMs(fail.duration_ms) }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ==================== 2. Curl / HTTP 与沙盒看板 ==================== -->
    <section v-if="httpTools && (activeTab === 'all' || activeTab === 'http')" class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Icon name="terminal" :size="16" class="text-accent" />
          <h2 class="text-[15px] font-semibold text-fg">Curl / HTTP 请求、网页抓取与沙盒执行看板</h2>
        </div>
        <span class="text-[12px] text-fg-muted">
          覆盖 <code class="font-mono">http_request</code>（等效 curl）、<code class="font-mono">web_extract</code> 与 <code class="font-mono">execute_code</code>
        </span>
      </div>

      <!-- Curl / HTTP & 伴随工具 KPI -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">HTTP / Curl 总次数</p>
          <p class="mt-1 text-xl font-semibold text-fg">
            {{ numberFormat.format(httpTools.http_request.summary.total) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            流量 {{ fmtBytes(httpTools.http_request.summary.total_bytes_read) }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">HTTP / Curl 成功率</p>
          <p class="mt-1 text-xl font-semibold" :class="rateTextClass(httpTools.http_request.summary.success_rate_pct)">
            {{ fmtPct(httpTools.http_request.summary.success_rate_pct) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            2xx/3xx {{ httpTools.http_request.summary.succeeded }} · 败 {{ httpTools.http_request.summary.failed }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">HTTP 平均 / P95 耗时</p>
          <p class="mt-1 text-xl font-semibold text-fg">
            {{ fmtMs(httpTools.http_request.summary.avg_duration_ms) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            P95: {{ fmtMs(httpTools.http_request.summary.p95_duration_ms) }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">4xx / 5xx / 网络拦截</p>
          <p class="mt-1 text-xl font-semibold text-fg">
            {{ httpTools.http_request.summary.http_4xx }}
            <span class="text-[13px] font-normal text-fg-muted">
              / {{ httpTools.http_request.summary.http_5xx }} / {{ httpTools.http_request.summary.network_errors }}
            </span>
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">含 SSRF 拦截与超时异常</p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">网页抓取 (web_extract)</p>
          <p class="mt-1 text-xl font-semibold" :class="rateTextClass(httpTools.web_extract.summary.success_rate_pct)">
            {{ fmtPct(httpTools.web_extract.summary.success_rate_pct) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            {{ httpTools.web_extract.summary.total }} 次 · 降级 {{ httpTools.web_extract.summary.fallback_count }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">沙盒代码 / Shell Curl</p>
          <p class="mt-1 text-xl font-semibold" :class="rateTextClass(httpTools.execute_code.summary.success_rate_pct)">
            {{ fmtPct(httpTools.execute_code.summary.success_rate_pct) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            共 {{ httpTools.execute_code.summary.total }} 次 · Shell curl {{ httpTools.execute_code.summary.curl_command_count }} · 拒批 {{ httpTools.execute_code.summary.denied }}
          </p>
        </div>
      </div>

      <!-- Curl / HTTP 每日趋势 + 状态码 & Method 分布 -->
      <div class="grid gap-4 lg:grid-cols-3">
        <div class="lg:col-span-2">
          <DailySuccessChart
            title="Curl / HTTP 请求每日调用量与成功率"
            subtitle="统计 http_request 工具的每日请求成功（2xx/3xx）与失败（4xx/5xx/网络/SSRF）趋势"
            :rows="httpDailyPoints"
          />
        </div>

        <div class="space-y-4 rounded-2xl border border-line bg-surface p-5">
          <div>
            <h3 class="mb-2.5 text-[14px] font-semibold text-fg">HTTP 状态码分布</h3>
            <div class="space-y-2 text-[12px]">
              <div
                v-for="sb in httpTools.http_request.by_status_bucket"
                :key="sb.bucket"
                class="flex items-center justify-between rounded-lg bg-canvas px-3 py-1.5"
              >
                <span class="text-fg">{{ STATUS_BUCKET_LABELS[sb.bucket] || sb.bucket }}</span>
                <span class="font-mono font-medium text-fg">{{ sb.count }}</span>
              </div>
            </div>
          </div>

          <div class="border-t border-line pt-3">
            <h3 class="mb-2 text-[13px] font-semibold text-fg">沙盒执行语言分布</h3>
            <div v-if="!httpTools.execute_code.by_language.length" class="text-[12px] text-fg-faint">
              暂无沙盒代码执行记录
            </div>
            <div v-else class="space-y-1.5 text-[12px]">
              <div
                v-for="lang in httpTools.execute_code.by_language"
                :key="lang.language"
                class="flex items-center justify-between"
              >
                <span class="font-mono text-fg">{{ lang.language }}</span>
                <span class="text-fg-muted">
                  {{ lang.total }} 次 · {{ fmtPct(lang.success_rate_pct) }} · {{ fmtMs(lang.avg_duration_ms) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Method 分布 + Top 目标域名 + 最近失败 -->
      <div class="grid gap-4 lg:grid-cols-3">
        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">HTTP Method 与网页抓取分布</h3>
          <div v-if="!httpTools.http_request.by_method.length" class="py-6 text-center text-[13px] text-fg-faint">
            暂无 HTTP 请求记录
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-[12px]">
              <thead>
                <tr class="border-b border-line text-fg-muted">
                  <th class="pb-2 font-medium">Method</th>
                  <th class="pb-2 text-right font-medium">次数</th>
                  <th class="pb-2 text-right font-medium">成功率</th>
                  <th class="pb-2 text-right font-medium">均耗</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="m in httpTools.http_request.by_method" :key="m.method">
                  <td class="py-1.5 font-mono font-medium text-fg">{{ m.method }}</td>
                  <td class="py-1.5 text-right text-fg-muted">{{ m.total }}</td>
                  <td class="py-1.5 text-right font-medium" :class="rateTextClass(m.success_rate_pct)">
                    {{ fmtPct(m.success_rate_pct) }}
                  </td>
                  <td class="py-1.5 text-right text-fg-muted">{{ fmtMs(m.avg_duration_ms) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="httpTools.web_extract.by_provider.length" class="mt-4 border-t border-line pt-3">
            <p class="mb-2 text-[12.5px] font-semibold text-fg">网页抓取引擎</p>
            <div class="space-y-1.5 text-[12px]">
              <div
                v-for="ep in httpTools.web_extract.by_provider"
                :key="ep.provider"
                class="flex items-center justify-between"
              >
                <span class="text-fg">{{ PROVIDER_LABELS[ep.provider] || ep.provider }}</span>
                <span class="text-fg-muted">
                  {{ ep.total }} 次 · {{ fmtPct(ep.success_rate_pct) }} · {{ fmtMs(ep.avg_duration_ms) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">Top 目标域名</h3>
          <div v-if="!httpTools.http_request.top_hosts.length" class="py-6 text-center text-[13px] text-fg-faint">
            暂无域名统计
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-[12px]">
              <thead>
                <tr class="border-b border-line text-fg-muted">
                  <th class="pb-2 font-medium">域名</th>
                  <th class="pb-2 text-right font-medium">次数</th>
                  <th class="pb-2 text-right font-medium">成功率</th>
                  <th class="pb-2 text-right font-medium">均耗</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="h in httpTools.http_request.top_hosts.slice(0, 10)" :key="h.host">
                  <td class="max-w-[160px] truncate py-1.5 font-mono text-fg">{{ h.host }}</td>
                  <td class="py-1.5 text-right text-fg-muted">{{ h.total }}</td>
                  <td class="py-1.5 text-right font-medium" :class="rateTextClass(h.success_rate_pct)">
                    {{ fmtPct(h.success_rate_pct) }}
                  </td>
                  <td class="py-1.5 text-right text-fg-muted">{{ fmtMs(h.avg_duration_ms) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">最近 HTTP / 沙盒失败记录</h3>
          <div
            v-if="!httpTools.http_request.recent_failures.length && !httpTools.execute_code.recent_failures.length"
            class="py-6 text-center text-[13px] text-fg-faint"
          >
            统计窗口内无失败记录
          </div>
          <div v-else class="max-h-72 space-y-2 overflow-y-auto pr-1">
            <div
              v-for="f in httpTools.http_request.recent_failures"
              :key="f.id"
              class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="font-mono font-medium text-fg">{{ f.method }} {{ f.host }}</span>
                <BaseBadge tone="red">{{ f.status_code ?? "ERR" }}</BaseBadge>
              </div>
              <p class="mt-0.5 truncate text-[11px] text-fg-muted">{{ f.url }}</p>
              <p class="mt-1 line-clamp-2 text-danger">{{ f.error }}</p>
              <p class="mt-1 text-[11px] text-fg-faint">
                {{ f.user_email }} · {{ fmtTime(f.created_at) }} · {{ fmtMs(f.duration_ms) }}
              </p>
            </div>
            <div
              v-for="cf in httpTools.execute_code.recent_failures"
              :key="cf.id"
              class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="font-mono font-medium text-fg">sandbox ({{ cf.language }})</span>
                <BaseBadge :tone="cf.status === 'denied' ? 'amber' : 'red'">
                  {{ cf.status === 'denied' ? '拒批' : `exit ${cf.exit_code ?? '?'}` }}
                </BaseBadge>
              </div>
              <p class="mt-1 line-clamp-2 text-danger">{{ cf.error }}</p>
              <p class="mt-1 text-[11px] text-fg-faint">
                {{ cf.user_email }} · {{ fmtTime(cf.created_at) }} · {{ fmtMs(cf.duration_ms) }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ==================== 3. 联网搜索看板 ==================== -->
    <section v-if="webSearch && (activeTab === 'all' || activeTab === 'search')" class="space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <Icon name="globe" :size="16" class="text-accent" />
          <h2 class="text-[15px] font-semibold text-fg">联网搜索看板 (web_search)</h2>
        </div>
        <span class="text-[12px] text-fg-muted">
          统计 博查 / Tavily / DuckDuckGo 搜索次数、成功率、有效命中率与引擎降级情况
        </span>
      </div>

      <!-- 联网搜索 KPI -->
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">联网搜索总次数</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ numberFormat.format(webSearch.summary.total) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            进行中 {{ webSearch.summary.in_progress }} · 均 {{ webSearch.summary.avg_results_per_search }} 条/次
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">搜索成功率</p>
          <p class="mt-1 text-xl font-semibold" :class="rateTextClass(webSearch.summary.success_rate_pct)">
            {{ fmtPct(webSearch.summary.success_rate_pct) }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            成功 {{ webSearch.summary.succeeded }} · 失败 {{ webSearch.summary.failed }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">有效命中率 (非空)</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ fmtPct(webSearch.summary.hit_rate_pct) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">
            有结果 {{ webSearch.summary.with_results }} · 空结果 {{ webSearch.summary.empty_results }}
          </p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">引擎降级回退次数</p>
          <p
            class="mt-1 text-xl font-semibold"
            :class="webSearch.summary.fallback_count > 0 ? 'text-warning' : 'text-fg'"
          >
            {{ webSearch.summary.fallback_count }}
          </p>
          <p class="mt-0.5 text-[11px] text-fg-faint">主引擎异常跨引擎或 DuckDuckGo 回退</p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">平均搜索耗时</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ fmtMs(webSearch.summary.avg_duration_ms) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">单次调用端到端耗时</p>
        </div>
        <div class="rounded-2xl border border-line bg-surface p-4">
          <p class="text-[12px] text-fg-muted">P95 搜索耗时</p>
          <p class="mt-1 text-xl font-semibold text-fg">{{ fmtMs(webSearch.summary.p95_duration_ms) }}</p>
          <p class="mt-0.5 text-[11px] text-fg-faint">95% 分位延迟</p>
        </div>
      </div>

      <!-- 每日趋势 + 引擎分布 -->
      <div class="grid gap-4 lg:grid-cols-3">
        <div class="lg:col-span-2">
          <DailySuccessChart
            title="每日联网搜索次数与成功率趋势"
            subtitle="包含搜索成功/失败次数、成功率折线及每日降级回退情况"
            :rows="searchDailyPoints"
          />
        </div>

        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">搜索引擎分布</h3>
          <div v-if="!webSearch.by_provider.length" class="py-8 text-center text-[13px] text-fg-faint">
            暂无引擎分布数据
          </div>
          <div v-else class="space-y-3">
            <div
              v-for="p in webSearch.by_provider"
              :key="p.provider"
              class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
            >
              <div class="flex items-center justify-between">
                <span class="font-medium text-fg">{{ PROVIDER_LABELS[p.provider] || p.provider }}</span>
                <BaseBadge :tone="rateTone(p.success_rate_pct)">{{ fmtPct(p.success_rate_pct) }}</BaseBadge>
              </div>
              <div class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-fg-muted">
                <span>总 {{ p.total }} 次</span>
                <span>成功 {{ p.succeeded }}</span>
                <span>失败 {{ p.failed }}</span>
                <span>空结果 {{ p.empty_results }}</span>
                <span v-if="p.fallback_count > 0" class="text-warning">降级 {{ p.fallback_count }}</span>
                <span>均耗 {{ fmtMs(p.avg_duration_ms) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近搜索与异常记录 -->
      <div class="grid gap-4 lg:grid-cols-2">
        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">最近联网搜索记录</h3>
          <div v-if="!webSearch.recent_searches.length" class="py-8 text-center text-[13px] text-fg-faint">
            暂无搜索记录
          </div>
          <div v-else class="overflow-x-auto">
            <table class="w-full text-left text-[12px]">
              <thead>
                <tr class="border-b border-line text-fg-muted">
                  <th class="pb-2 font-medium">查询词</th>
                  <th class="pb-2 font-medium">引擎</th>
                  <th class="pb-2 text-right font-medium">结果数</th>
                  <th class="pb-2 text-right font-medium">状态</th>
                  <th class="pb-2 text-right font-medium">耗时</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-for="s in webSearch.recent_searches" :key="s.id">
                  <td class="py-2 pr-2">
                    <p class="max-w-[220px] truncate font-medium text-fg">{{ s.query }}</p>
                    <p class="text-[11px] text-fg-faint">{{ s.user_email }} · {{ fmtTime(s.created_at) }}</p>
                  </td>
                  <td class="py-2 pr-2">
                    <BaseBadge :tone="s.fallback_from ? 'amber' : 'gray'">
                      {{ s.provider }}{{ s.fallback_from ? " (降级)" : "" }}
                    </BaseBadge>
                  </td>
                  <td class="py-2 text-right font-mono text-fg-muted">{{ s.result_count }}</td>
                  <td class="py-2 text-right">
                    <BaseBadge :tone="s.status === 'completed' ? (s.result_count > 0 ? 'green' : 'amber') : 'red'">
                      {{ s.status === 'completed' ? (s.result_count > 0 ? '成功' : '空结果') : '失败' }}
                    </BaseBadge>
                  </td>
                  <td class="py-2 text-right text-fg-muted">{{ fmtMs(s.duration_ms) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="rounded-2xl border border-line bg-surface p-5">
          <h3 class="mb-3 text-[14px] font-semibold text-fg">搜索失败 / 零结果排查</h3>
          <div v-if="!webSearch.recent_failures.length" class="py-8 text-center text-[13px] text-fg-faint">
            统计窗口内无失败或零结果记录
          </div>
          <div v-else class="max-h-80 space-y-2 overflow-y-auto pr-1">
            <div
              v-for="sf in webSearch.recent_failures"
              :key="sf.id"
              class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
            >
              <div class="flex items-center justify-between gap-2">
                <span class="truncate font-medium text-fg">{{ sf.query }}</span>
                <BaseBadge :tone="sf.status === 'failed' ? 'red' : 'amber'">
                  {{ sf.status === 'failed' ? '失败' : '0 结果' }}
                </BaseBadge>
              </div>
              <p v-if="sf.error" class="mt-1 line-clamp-2 text-danger">{{ sf.error }}</p>
              <p class="mt-1 text-[11px] text-fg-faint">
                引擎: {{ sf.provider }}
                <span v-if="sf.fallback_from"> (从 {{ sf.fallback_from }} 降级)</span>
                · {{ sf.user_email }} · {{ fmtTime(sf.created_at) }} · {{ fmtMs(sf.duration_ms) }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
