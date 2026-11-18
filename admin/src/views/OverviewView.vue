<script setup lang="ts">
import { computed, onMounted, ref, useId } from "vue";
import { api, readableError } from "../api/client";
import type {
  AdminActiveRun,
  AdminAnalytics,
  AdminMonitor,
  AuditLog,
  AuditLogList,
  Overview,
} from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

type ChartTab = "tokens" | "messages" | "users";
type DayWindow = 7 | 14 | 30;

const CHART_W = 720;
const CHART_H = 228;
const PAD_L = 52;
const PAD_R = 48;
const PAD_T = 16;
const PAD_B = 28;
const PLOT_W = CHART_W - PAD_L - PAD_R;
const PLOT_H = CHART_H - PAD_T - PAD_B;

const gradId = useId();
const data = ref<Overview | null>(null);
const recent = ref<AuditLog[]>([]);
const analytics = ref<AdminAnalytics | null>(null);
const monitor = ref<AdminMonitor | null>(null);

const selectedDays = ref<DayWindow>(14);
const chartTab = ref<ChartTab>("tokens");
const hoverIndex = ref<number | null>(null);

const loading = ref(false);
const analyticsLoading = ref(false);
const monitorLoading = ref(false);
const error = ref<string | null>(null);
const analyticsError = ref<string | null>(null);
const monitorError = ref<string | null>(null);

const stopTarget = ref<AdminActiveRun | null>(null);
const stopLoading = ref(false);
const stopError = ref<string | null>(null);

const numberFormat = new Intl.NumberFormat("zh-CN");
let analyticsSeq = 0;

const stats = computed(() => {
  const o = data.value;
  if (!o) return [];
  return [
    { label: "用户总数", value: o.users.total, hint: `活跃 ${o.users.active}` },
    { label: "今日消息", value: o.usage_today.messages, hint: `运行 ${o.usage_today.runs} 次` },
    { label: "今日 Token", value: o.usage_today.tokens, hint: `≈ ${o.credits_today.used} 积分` },
    { label: "今日积分消耗", value: o.credits_today.used, hint: `1 积分 = ${numberFormat.format(o.credits_today.tokens_per_credit)} tokens` },
    { label: "付费会员", value: o.membership.plus + o.membership.pro, hint: `Free ${o.membership.free}` },
    { label: "活跃任务", value: o.conversations.active_runs, hint: `会话 ${o.conversations.total}` },
    { label: "今日新增用户", value: o.users.new_today, hint: `管理员 ${o.users.admins}` },
    { label: "近 24h 失败操作", value: o.audit_24h.failures, hint: "审计日志" },
    { label: "近 24h 严重事件", value: o.audit_24h.critical, hint: "审计日志" },
  ];
});

const distribution = computed(() => {
  const o = data.value;
  if (!o) return [];
  const total = Math.max(1, o.membership.free + o.membership.plus + o.membership.pro);
  return (["free", "plus", "pro"] as const).map((tier) => ({
    tier,
    label: tier === "free" ? "Free" : tier === "plus" ? "Plus" : "Pro",
    count: o.membership[tier],
    width: `${Math.round((o.membership[tier] / total) * 100)}%`,
    tone: tier === "pro" ? "bg-[#7C6BF0]" : tier === "plus" ? "bg-accent" : "bg-line-strong",
  }));
});

function niceMax(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 4;
  if (raw <= 4) return 4;
  if (raw <= 8) return 8;
  if (raw <= 12) return 12;
  if (raw <= 16) return 16;
  if (raw <= 20) return 20;
  const exp = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / exp;
  const nice = norm <= 1.2 ? 1.2 : norm <= 1.6 ? 1.6 : norm <= 2 ? 2 : norm <= 4 ? 4 : norm <= 6 ? 6 : norm <= 8 ? 8 : 10;
  return nice * exp;
}

function formatAxis(val: number): string {
  if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (val >= 10_000) return `${(val / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  if (Number.isInteger(val)) return numberFormat.format(val);
  return val.toFixed(1).replace(/\.0$/, "");
}

function formatDecimal(val: number): string {
  if (Number.isInteger(val)) return numberFormat.format(val);
  return val.toFixed(2).replace(/\.?0+$/, "");
}

const chartMeta = computed(() => {
  const days = analytics.value?.daily ?? [];
  if (chartTab.value === "tokens") {
    return {
      primaryLabel: "Token 消耗",
      secondaryLabel: "积分消耗",
      primaryKey: "tokens" as const,
      secondaryKey: "credits" as const,
      dualAxis: true,
      mode: "bar-line" as const,
      primaryColor: "var(--accent)",
      secondaryColor: "#7C6BF0",
      days,
    };
  }
  if (chartTab.value === "messages") {
    return {
      primaryLabel: "消息数",
      secondaryLabel: "运行次数",
      primaryKey: "messages" as const,
      secondaryKey: "runs" as const,
      dualAxis: false,
      mode: "dual-line" as const,
      primaryColor: "var(--accent)",
      secondaryColor: "var(--success)",
      days,
    };
  }
  return {
    primaryLabel: "活跃用户",
    secondaryLabel: "新增用户",
    primaryKey: "active_users" as const,
    secondaryKey: "new_users" as const,
    dualAxis: false,
    mode: "dual-line" as const,
    primaryColor: "var(--accent)",
    secondaryColor: "var(--warning)",
    days,
  };
});

const chartGeometry = computed(() => {
  const meta = chartMeta.value;
  const rows = meta.days;
  const n = rows.length;
  const rawPrimary = rows.map((r) => Number(r[meta.primaryKey] || 0));
  const rawSecondary = rows.map((r) => Number(r[meta.secondaryKey] || 0));

  const maxPrimaryRaw = Math.max(0, ...rawPrimary);
  const maxSecondaryRaw = Math.max(0, ...rawSecondary);

  const leftMax = meta.dualAxis ? niceMax(maxPrimaryRaw) : niceMax(Math.max(maxPrimaryRaw, maxSecondaryRaw));
  const rightMax = meta.dualAxis ? niceMax(maxSecondaryRaw) : leftMax;

  const slotW = n > 0 ? PLOT_W / n : PLOT_W;
  const barW = Math.max(4, Math.min(24, slotW * 0.56));

  const points = rows.map((row, i) => {
    const pv = rawPrimary[i] ?? 0;
    const sv = rawSecondary[i] ?? 0;
    const x = PAD_L + slotW * (i + 0.5);
    const y1 = PAD_T + PLOT_H - (pv / leftMax) * PLOT_H;
    const y2 = PAD_T + PLOT_H - (sv / rightMax) * PLOT_H;
    return {
      index: i,
      day: row.day,
      shortDay: row.day.slice(5),
      primary: pv,
      secondary: sv,
      x,
      y1,
      y2,
      barX: x - barW / 2,
      barY: y1,
      barH: Math.max(0, PAD_T + PLOT_H - y1),
      slotX: PAD_L + i * slotW,
      slotW,
    };
  });

  const gridTicks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
    y: PAD_T + PLOT_H * (1 - ratio),
    leftLabel: formatAxis(leftMax * ratio),
    rightLabel: formatAxis(rightMax * ratio),
  }));

  const primaryLine = points.map((p) => `${p.x.toFixed(1)},${p.y1.toFixed(1)}`).join(" ");
  const secondaryLine = points.map((p) => `${p.x.toFixed(1)},${p.y2.toFixed(1)}`).join(" ");
  const areaPath =
    points.length > 0
      ? `M ${points[0]!.x.toFixed(1)} ${(PAD_T + PLOT_H).toFixed(1)} ` +
        points.map((p) => `L ${p.x.toFixed(1)} ${p.y1.toFixed(1)}`).join(" ") +
        ` L ${points[points.length - 1]!.x.toFixed(1)} ${(PAD_T + PLOT_H).toFixed(1)} Z`
      : "";

  const labelStep = n <= 8 ? 1 : n <= 16 ? 2 : 5;
  const xLabels = points.filter((_, idx) => {
    if (idx === n - 1) return true;
    if (idx % labelStep === 0 && n - 1 - idx >= Math.ceil(labelStep / 2)) return true;
    return false;
  });

  return {
    points,
    barW,
    gridTicks,
    primaryLine,
    secondaryLine,
    areaPath,
    xLabels,
  };
});

const hoveredPoint = computed(() => {
  if (hoverIndex.value === null) return null;
  return chartGeometry.value.points[hoverIndex.value] ?? null;
});

const tooltipStyle = computed(() => {
  const pt = hoveredPoint.value;
  if (!pt) return {};
  const pct = (pt.x / CHART_W) * 100;
  if (pct > 62) {
    return {
      right: `${(100 - pct + 1.5).toFixed(2)}%`,
      top: "8px",
    };
  }
  return {
    left: `${(pct + 1.5).toFixed(2)}%`,
    top: "8px",
  };
});

const servicePills = computed(() => {
  const s = monitor.value?.services;
  if (!s) return [];
  return [
    { key: "postgres", label: "PostgreSQL", ok: s.postgres, okText: "正常", failText: "异常", warnOnFail: false },
    { key: "redis", label: "Redis", ok: s.redis, okText: "正常", failText: "异常", warnOnFail: false },
    { key: "hermes", label: "Hermes", ok: s.hermes, okText: "正常", failText: "异常", warnOnFail: false },
    { key: "cos", label: "COS 存储", ok: s.cos_configured, okText: "已配置", failText: "未配置", warnOnFail: true },
    { key: "smtp", label: "SMTP 邮件", ok: s.smtp_configured, okText: "已配置", failText: "未配置", warnOnFail: true },
  ];
});

const stalledCount = computed(() => monitor.value?.active_runs.filter((r) => r.is_stalled).length ?? 0);

function planCredits(weekly: number, fiveHour: number | null): string {
  const fiveHourText = fiveHour === null ? "5 小时不限" : `5 小时 ${numberFormat.format(fiveHour)}`;
  return `周 ${numberFormat.format(weekly)} · ${fiveHourText}`;
}

function fmt(value: number): string {
  return numberFormat.format(value);
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const idx = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const val = bytes / 1024 ** idx;
  return `${val >= 100 || idx === 0 ? val.toFixed(0) : val.toFixed(1)} ${units[idx]}`;
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} 秒`;
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  if (mins < 60) return secs > 0 ? `${mins} 分 ${secs} 秒` : `${mins} 分钟`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins > 0 ? `${hours} 小时 ${remMins} 分` : `${hours} 小时`;
}

function tierLabel(tier: string): string {
  const lower = tier.toLowerCase();
  if (lower === "pro") return "Pro";
  if (lower === "plus") return "Plus";
  return "Free";
}

function tierTone(tier: string): "brand" | "blue" | "gray" {
  const lower = tier.toLowerCase();
  if (lower === "pro") return "brand";
  if (lower === "plus") return "blue";
  return "gray";
}

async function loadAnalytics(days = selectedDays.value) {
  const seq = ++analyticsSeq;
  analyticsLoading.value = true;
  analyticsError.value = null;
  hoverIndex.value = null;
  try {
    const res = await api.get<AdminAnalytics>(`/admin/analytics?days=${days}`);
    if (seq !== analyticsSeq) return;
    analytics.value = res;
  } catch (e: unknown) {
    if (seq !== analyticsSeq) return;
    analyticsError.value = readableError(e);
  } finally {
    if (seq === analyticsSeq) analyticsLoading.value = false;
  }
}

async function loadMonitor() {
  monitorLoading.value = true;
  monitorError.value = null;
  try {
    monitor.value = await api.get<AdminMonitor>("/admin/monitor");
  } catch (e: unknown) {
    monitorError.value = readableError(e);
  } finally {
    monitorLoading.value = false;
  }
}

async function loadOverview() {
  error.value = null;
  const [overviewRes, auditsRes] = await Promise.allSettled([
    api.get<Overview>("/admin/overview"),
    api.get<AuditLogList>("/admin/audit-logs?page=1&page_size=8"),
  ]);
  if (overviewRes.status === "fulfilled") {
    data.value = overviewRes.value;
  } else {
    error.value = readableError(overviewRes.reason);
  }
  if (auditsRes.status === "fulfilled") {
    recent.value = auditsRes.value.items;
  } else if (!error.value) {
    error.value = readableError(auditsRes.reason);
  }
}

async function load() {
  loading.value = true;
  await Promise.allSettled([loadOverview(), loadAnalytics(selectedDays.value), loadMonitor()]);
  loading.value = false;
}

function selectDays(days: DayWindow) {
  if (selectedDays.value === days) return;
  selectedDays.value = days;
  void loadAnalytics(days);
}

function askForceStop(run: AdminActiveRun) {
  stopError.value = null;
  stopTarget.value = run;
}

async function confirmForceStop() {
  const target = stopTarget.value;
  if (!target) return;
  stopLoading.value = true;
  stopError.value = null;
  try {
    await api.post(`/admin/conversations/${target.conversation_id}/stop`);
    stopTarget.value = null;
    await Promise.allSettled([loadMonitor(), loadOverview()]);
  } catch (e: unknown) {
    stopError.value = readableError(e);
  } finally {
    stopLoading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div>
    <div class="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-[20px] font-semibold tracking-tight text-fg">概览</h1>
        <p v-if="data" class="mt-1 text-[12px] tabular-nums text-fg-faint">
          统计更新于 {{ fmtTime(data.generated_at) }}
        </p>
        <p v-else class="mt-1 text-[12px] text-fg-faint">平台运行状态与今日用量</p>
      </div>
      <BaseButton variant="secondary" size="sm" :loading="loading" @click="load">
        <Icon name="refresh" :size="14" />
        刷新
      </BaseButton>
    </div>

    <p v-if="error" class="mb-4 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

    <div v-if="!data && loading" class="rounded-2xl border border-line px-4 py-16 text-center text-[13px] text-fg-faint">
      加载中…
    </div>

    <template v-else>
      <!-- Existing 9 KPI Cards -->
      <div v-if="data" class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div v-for="s in stats" :key="s.label" class="rounded-2xl border border-line bg-canvas p-4">
          <p class="text-[12px] text-fg-muted">{{ s.label }}</p>
          <p class="mt-2 text-[26px] font-semibold leading-none tabular-nums tracking-tight text-fg">
            {{ fmt(s.value) }}
          </p>
          <p class="mt-2 text-[11px] text-fg-faint">{{ s.hint }}</p>
        </div>
      </div>

      <!-- Analytics Trends -->
      <section class="mt-6 rounded-2xl border border-line bg-canvas p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-[14px] font-medium text-fg">趋势分析</h2>
              <span v-if="analytics" class="text-[11.5px] tabular-nums text-fg-faint">
                {{ analytics.start_day }} ~ {{ analytics.end_day }}
              </span>
            </div>
            <div v-if="analytics" class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] tabular-nums text-fg-muted">
              <span>Token <strong class="font-medium text-fg">{{ fmt(analytics.summary.total_tokens ?? 0) }}</strong></span>
              <span>积分 <strong class="font-medium text-fg">{{ formatDecimal(analytics.summary.total_credits ?? 0) }}</strong></span>
              <span>消息 <strong class="font-medium text-fg">{{ fmt(analytics.summary.total_messages ?? 0) }}</strong></span>
              <span>运行 <strong class="font-medium text-fg">{{ fmt(analytics.summary.total_runs ?? 0) }}</strong></span>
              <span>新增 <strong class="font-medium text-fg">{{ fmt(analytics.summary.total_new_users ?? 0) }}</strong></span>
              <span>活跃 <strong class="font-medium text-fg">{{ fmt(analytics.summary.active_users ?? 0) }}</strong></span>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <div class="inline-flex rounded-xl border border-line bg-surface p-0.5">
              <button
                v-for="tab in ([
                  { key: 'tokens', label: 'Token / 积分' },
                  { key: 'messages', label: '消息 / 运行' },
                  { key: 'users', label: '新增 / 活跃用户' },
                ] as const)"
                :key="tab.key"
                type="button"
                class="focus-ring rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors"
                :class="chartTab === tab.key ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
                @click="chartTab = tab.key"
              >
                {{ tab.label }}
              </button>
            </div>

            <div class="inline-flex rounded-xl border border-line bg-surface p-0.5">
              <button
                v-for="d in ([7, 14, 30] as const)"
                :key="d"
                type="button"
                class="focus-ring rounded-lg px-2.5 py-1 text-[12px] font-medium tabular-nums transition-colors"
                :class="selectedDays === d ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
                @click="selectDays(d)"
              >
                {{ d }}天
              </button>
            </div>
          </div>
        </div>

        <p v-if="analyticsError" class="mt-3 rounded-xl bg-danger-weak px-3 py-2 text-[12.5px] text-danger">
          {{ analyticsError }}
        </p>

        <div v-else-if="analyticsLoading && !analytics" class="py-16 text-center text-[13px] text-fg-faint">
          加载趋势数据中…
        </div>

        <div v-else-if="analytics" class="mt-4">
          <div class="mb-2 flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-fg-muted">
            <div class="flex items-center gap-4">
              <span class="inline-flex items-center gap-1.5">
                <span
                  class="inline-block h-2 w-2 rounded-sm"
                  :style="{ backgroundColor: chartMeta.primaryColor }"
                />
                {{ chartMeta.primaryLabel }}
              </span>
              <span class="inline-flex items-center gap-1.5">
                <span
                  class="inline-block h-2 w-2 rounded-full"
                  :style="{ backgroundColor: chartMeta.secondaryColor }"
                />
                {{ chartMeta.secondaryLabel }}
              </span>
            </div>
            <span v-if="analyticsLoading" class="text-[11px] text-fg-faint">更新中…</span>
          </div>

          <div v-if="!chartGeometry.points.length" class="rounded-xl border border-line py-12 text-center text-[12.5px] text-fg-faint">
            暂无趋势数据
          </div>

          <div v-else class="relative w-full">
            <svg
              :viewBox="`0 0 ${CHART_W} ${CHART_H}`"
              class="h-56 w-full select-none overflow-visible"
              role="img"
              :aria-label="`${selectedDays}天${chartMeta.primaryLabel}与${chartMeta.secondaryLabel}趋势图`"
              @mouseleave="hoverIndex = null"
            >
              <defs>
                <linearGradient :id="`area-${gradId}`" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.22" />
                  <stop offset="100%" stop-color="var(--accent)" stop-opacity="0" />
                </linearGradient>
              </defs>

              <!-- Horizontal grid lines + Y axis ticks -->
              <g v-for="tick in chartGeometry.gridTicks" :key="tick.y">
                <line
                  :x1="PAD_L"
                  :x2="CHART_W - PAD_R"
                  :y1="tick.y"
                  :y2="tick.y"
                  stroke="var(--line)"
                  stroke-dasharray="3 3"
                  stroke-width="1"
                />
                <text
                  :x="PAD_L - 8"
                  :y="tick.y + 3.5"
                  text-anchor="end"
                  fill="var(--fg-faint)"
                  font-size="10.5"
                  class="tabular-nums"
                >
                  {{ tick.leftLabel }}
                </text>
                <text
                  v-if="chartMeta.dualAxis"
                  :x="CHART_W - PAD_R + 8"
                  :y="tick.y + 3.5"
                  text-anchor="start"
                  fill="var(--fg-faint)"
                  font-size="10.5"
                  class="tabular-nums"
                >
                  {{ tick.rightLabel }}
                </text>
              </g>

              <!-- Series rendering: bar + line for Tokens/Credits; area + dual lines for others -->
              <template v-if="chartMeta.mode === 'bar-line'">
                <rect
                  v-for="pt in chartGeometry.points"
                  :key="`bar-${pt.day}`"
                  :x="pt.barX"
                  :y="pt.barY"
                  :width="chartGeometry.barW"
                  :height="pt.barH"
                  rx="3"
                  fill="var(--accent)"
                  :fill-opacity="hoverIndex === pt.index ? 0.5 : 0.22"
                />
                <polyline
                  fill="none"
                  :stroke="chartMeta.secondaryColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  :points="chartGeometry.secondaryLine"
                />
              </template>
              <template v-else>
                <path :d="chartGeometry.areaPath" :fill="`url(#area-${gradId})`" />
                <polyline
                  fill="none"
                  :stroke="chartMeta.primaryColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  :points="chartGeometry.primaryLine"
                />
                <polyline
                  fill="none"
                  :stroke="chartMeta.secondaryColor"
                  stroke-width="2"
                  stroke-dasharray="4 3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  :points="chartGeometry.secondaryLine"
                />
              </template>

              <!-- X axis labels -->
              <text
                v-for="lbl in chartGeometry.xLabels"
                :key="`x-${lbl.day}`"
                :x="lbl.x"
                :y="CHART_H - 6"
                text-anchor="middle"
                fill="var(--fg-faint)"
                font-size="10.5"
                class="tabular-nums"
              >
                {{ lbl.shortDay }}
              </text>

              <!-- Active crosshair & dots -->
              <g v-if="hoveredPoint" class="pointer-events-none">
                <line
                  :x1="hoveredPoint.x"
                  :x2="hoveredPoint.x"
                  :y1="PAD_T"
                  :y2="PAD_T + PLOT_H"
                  stroke="var(--line-strong)"
                  stroke-width="1"
                />
                <circle
                  v-if="chartMeta.mode !== 'bar-line'"
                  :cx="hoveredPoint.x"
                  :cy="hoveredPoint.y1"
                  r="4.5"
                  :fill="chartMeta.primaryColor"
                  stroke="var(--canvas)"
                  stroke-width="2"
                />
                <circle
                  :cx="hoveredPoint.x"
                  :cy="hoveredPoint.y2"
                  r="4.5"
                  :fill="chartMeta.secondaryColor"
                  stroke="var(--canvas)"
                  stroke-width="2"
                />
              </g>

              <!-- Interactive hit columns -->
              <rect
                v-for="pt in chartGeometry.points"
                :key="`hit-${pt.day}`"
                :x="pt.slotX"
                :y="PAD_T"
                :width="pt.slotW"
                :height="PLOT_H"
                fill="transparent"
                tabindex="0"
                class="cursor-crosshair outline-none"
                :aria-label="`${pt.day} ${chartMeta.primaryLabel} ${pt.primary} ${chartMeta.secondaryLabel} ${pt.secondary}`"
                @mouseenter="hoverIndex = pt.index"
                @focus="hoverIndex = pt.index"
                @blur="hoverIndex = null"
              />
            </svg>

            <!-- Hover Tooltip -->
            <div
              v-if="hoveredPoint"
              class="pointer-events-none absolute z-10 min-w-[164px] rounded-xl border border-line bg-canvas/95 px-3 py-2 text-[11.5px] backdrop-blur-xs"
              style="box-shadow: var(--shadow)"
              :style="tooltipStyle"
            >
              <p class="font-medium tabular-nums text-fg">{{ hoveredPoint.day }}</p>
              <div class="mt-1.5 space-y-1 tabular-nums">
                <div class="flex items-center justify-between gap-3">
                  <span class="flex items-center gap-1.5 text-fg-muted">
                    <span class="h-1.5 w-1.5 rounded-full" :style="{ backgroundColor: chartMeta.primaryColor }" />
                    {{ chartMeta.primaryLabel }}
                  </span>
                  <span class="font-medium text-fg">{{ fmt(hoveredPoint.primary) }}</span>
                </div>
                <div class="flex items-center justify-between gap-3">
                  <span class="flex items-center gap-1.5 text-fg-muted">
                    <span class="h-1.5 w-1.5 rounded-full" :style="{ backgroundColor: chartMeta.secondaryColor }" />
                    {{ chartMeta.secondaryLabel }}
                  </span>
                  <span class="font-medium text-fg">
                    {{ chartMeta.secondaryKey === "credits" ? formatDecimal(hoveredPoint.secondary) : fmt(hoveredPoint.secondary) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- Top Users + Workspace File Summary -->
      <div v-if="analytics" class="mt-4 grid gap-4 lg:grid-cols-3">
        <section class="overflow-hidden rounded-2xl border border-line bg-canvas lg:col-span-2">
          <div class="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 class="text-[13.5px] font-medium text-fg">用量 Top 用户（近 {{ analytics.days }} 天）</h2>
            <span class="text-[11.5px] tabular-nums text-fg-faint">Top {{ analytics.top_users.length }}</span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full min-w-[560px] text-sm">
              <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
                <tr>
                  <th class="px-4 py-2.5 font-medium">用户</th>
                  <th class="px-4 py-2.5 font-medium">档位</th>
                  <th class="px-4 py-2.5 text-right font-medium">消息</th>
                  <th class="px-4 py-2.5 text-right font-medium">运行</th>
                  <th class="px-4 py-2.5 text-right font-medium">Tokens</th>
                  <th class="px-4 py-2.5 text-right font-medium">折算积分</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-line">
                <tr v-if="!analytics.top_users.length">
                  <td colspan="6" class="px-4 py-10 text-center text-[13px] text-fg-faint">该时间段暂无用量记录</td>
                </tr>
                <tr v-for="(u, idx) in analytics.top_users" :key="u.user_id" class="hover:bg-surface/60">
                  <td class="px-4 py-2.5">
                    <div class="flex items-center gap-2">
                      <span class="w-4 text-[11px] font-medium tabular-nums text-fg-faint">{{ idx + 1 }}</span>
                      <div class="min-w-0">
                        <p class="truncate text-[12.5px] font-medium text-fg">{{ u.display_name }}</p>
                        <p class="truncate text-[11px] text-fg-faint">{{ u.email }}</p>
                      </div>
                    </div>
                  </td>
                  <td class="px-4 py-2.5">
                    <BaseBadge :tone="tierTone(u.membership_tier)">{{ tierLabel(u.membership_tier) }}</BaseBadge>
                  </td>
                  <td class="px-4 py-2.5 text-right text-[12px] tabular-nums text-fg-muted">{{ fmt(u.messages) }}</td>
                  <td class="px-4 py-2.5 text-right text-[12px] tabular-nums text-fg-muted">{{ fmt(u.runs) }}</td>
                  <td class="px-4 py-2.5 text-right text-[12px] font-medium tabular-nums text-fg">{{ fmt(u.tokens) }}</td>
                  <td class="px-4 py-2.5 text-right text-[12px] tabular-nums text-fg-muted">
                    {{ formatDecimal(u.credits) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="rounded-2xl border border-line bg-canvas p-4">
          <div class="flex items-center justify-between gap-2">
            <h2 class="text-[13.5px] font-medium text-fg">工作区文件概览</h2>
            <Icon name="file" :size="15" class="text-fg-faint" />
          </div>

          <div class="mt-3 grid grid-cols-2 gap-2.5">
            <div class="rounded-xl border border-line bg-surface/40 px-3 py-2.5">
              <p class="text-[11px] text-fg-faint">就绪文件</p>
              <p class="mt-1 text-[20px] font-semibold tabular-nums text-fg">
                {{ fmt(analytics.file_stats.total_files ?? 0) }}
              </p>
            </div>
            <div class="rounded-xl border border-line bg-surface/40 px-3 py-2.5">
              <p class="text-[11px] text-fg-faint">总存储空间</p>
              <p class="mt-1 text-[20px] font-semibold tabular-nums text-fg">
                {{ formatBytes(analytics.file_stats.total_bytes ?? 0) }}
              </p>
            </div>
          </div>

          <dl class="mt-3 space-y-2 border-t border-line pt-3 text-[12px]">
            <div class="flex items-center justify-between">
              <dt class="text-fg-muted">全局共享文件</dt>
              <dd class="font-medium tabular-nums text-fg">{{ fmt(analytics.file_stats.global_files ?? 0) }}</dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-fg-muted">AI 生成产物</dt>
              <dd class="font-medium tabular-nums text-fg">{{ fmt(analytics.file_stats.assistant_files ?? 0) }}</dd>
            </div>
            <div class="flex items-center justify-between">
              <dt class="text-fg-muted">待完成 / 待清理上传</dt>
              <dd class="font-medium tabular-nums text-fg">
                <BaseBadge :tone="(analytics.file_stats.pending_files ?? 0) > 0 ? 'amber' : 'gray'">
                  {{ fmt(analytics.file_stats.pending_files ?? 0) }}
                </BaseBadge>
              </dd>
            </div>
          </dl>

          <p class="mt-4 border-t border-line pt-3 text-[11px] leading-relaxed text-fg-faint">
            当前换算比例：1 积分 = {{ fmt(analytics.tokens_per_credit) }} tokens。
          </p>
        </section>
      </div>

      <!-- Runtime & Anomaly Monitor -->
      <section class="mt-6 rounded-2xl border border-line bg-canvas p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <Icon name="activity" :size="16" class="text-fg-muted" />
            <h2 class="text-[14px] font-medium text-fg">运行监控与异常告警</h2>
            <BaseBadge v-if="monitor && stalledCount > 0" tone="red">
              {{ stalledCount }} 个疑似阻塞
            </BaseBadge>
            <BaseBadge v-else-if="monitor" tone="green">运行正常</BaseBadge>
          </div>
          <BaseButton size="sm" variant="ghost" :loading="monitorLoading" @click="loadMonitor">
            <Icon name="refresh" :size="13" />
            刷新监控
          </BaseButton>
        </div>

        <p v-if="monitorError" class="mt-3 rounded-xl bg-danger-weak px-3 py-2 text-[12.5px] text-danger">
          {{ monitorError }}
        </p>

        <div v-else-if="monitorLoading && !monitor" class="py-12 text-center text-[13px] text-fg-faint">
          检查服务与任务状态中…
        </div>

        <template v-else-if="monitor">
          <!-- Service Health Status Pills -->
          <div class="mt-3 flex flex-wrap gap-2">
            <div
              v-for="svc in servicePills"
              :key="svc.key"
              class="inline-flex items-center gap-2 rounded-full border border-line bg-surface/50 px-3 py-1 text-[12px]"
            >
              <span
                class="h-2 w-2 rounded-full"
                :class="svc.ok ? 'bg-success' : svc.warnOnFail ? 'bg-warning' : 'bg-danger'"
              />
              <span class="font-medium text-fg">{{ svc.label }}</span>
              <span :class="svc.ok ? 'text-success' : svc.warnOnFail ? 'text-warning' : 'text-danger'">
                {{ svc.ok ? svc.okText : svc.failText }}
              </span>
            </div>
          </div>

          <!-- Active / Stalled Runs Table -->
          <div class="mt-4 overflow-hidden rounded-xl border border-line">
            <div class="flex items-center justify-between border-b border-line bg-surface/40 px-4 py-2.5">
              <h3 class="text-[12.5px] font-medium text-fg">活跃任务（{{ monitor.active_runs.length }}）</h3>
              <span v-if="data" class="text-[11px] tabular-nums text-fg-faint">
                全局并发上限 {{ data.limits.max_concurrent_runs }} · 单用户 {{ data.limits.max_concurrent_runs_per_user }}
              </span>
            </div>

            <div class="overflow-x-auto">
              <table class="w-full min-w-[680px] text-sm">
                <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
                  <tr>
                    <th class="px-4 py-2.5 font-medium">会话 / Run ID</th>
                    <th class="px-4 py-2.5 font-medium">用户</th>
                    <th class="px-4 py-2.5 font-medium">状态</th>
                    <th class="px-4 py-2.5 font-medium">持续时长</th>
                    <th class="px-4 py-2.5 font-medium">健康度</th>
                    <th class="px-4 py-2.5 text-right font-medium">操作</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-line">
                  <tr v-if="!monitor.active_runs.length">
                    <td colspan="6" class="px-4 py-8 text-center text-[12.5px] text-fg-faint">当前没有运行中的任务</td>
                  </tr>
                  <tr v-for="run in monitor.active_runs" :key="run.conversation_id" class="hover:bg-surface/60">
                    <td class="px-4 py-2.5">
                      <p class="max-w-[220px] truncate text-[12.5px] font-medium text-fg">{{ run.title || "未命名会话" }}</p>
                      <p class="max-w-[220px] truncate font-mono text-[10.5px] text-fg-faint">{{ run.active_run_id }}</p>
                    </td>
                    <td class="px-4 py-2.5">
                      <p class="text-[12.5px] text-fg">{{ run.user_display_name }}</p>
                      <p class="text-[11px] text-fg-faint">{{ run.user_email }}</p>
                    </td>
                    <td class="px-4 py-2.5">
                      <BaseBadge tone="blue">{{ run.active_run_status || "running" }}</BaseBadge>
                      <p class="mt-0.5 text-[10.5px] tabular-nums text-fg-faint">{{ fmtTime(run.last_message_at) }}</p>
                    </td>
                    <td class="whitespace-nowrap px-4 py-2.5 text-[12px] tabular-nums text-fg">
                      {{ formatDuration(run.duration_seconds) }}
                    </td>
                    <td class="px-4 py-2.5">
                      <BaseBadge :tone="run.is_stalled ? 'red' : 'green'">
                        {{ run.is_stalled ? "疑似阻塞" : "运行中" }}
                      </BaseBadge>
                    </td>
                    <td class="px-4 py-2.5 text-right">
                      <BaseButton size="sm" variant="danger" @click="askForceStop(run)">强制停止</BaseButton>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 24h Failure Spike Summary -->
          <div class="mt-4 grid gap-3 lg:grid-cols-3">
            <div class="rounded-xl border border-line bg-canvas p-3.5">
              <div class="flex items-center justify-between">
                <h3 class="text-[12.5px] font-medium text-fg">24h 失败操作分布</h3>
                <Icon name="alert" :size="14" class="text-fg-faint" />
              </div>
              <p v-if="!monitor.failure_spikes_24h.length" class="mt-4 py-4 text-center text-[12px] text-fg-faint">
                近 24 小时无失败操作
              </p>
              <ul v-else class="mt-2.5 divide-y divide-line text-[12px]">
                <li
                  v-for="item in monitor.failure_spikes_24h"
                  :key="item.action"
                  class="flex items-center justify-between gap-2 py-2"
                >
                  <div class="min-w-0">
                    <p class="truncate font-mono text-[11.5px] text-fg">{{ item.action }}</p>
                    <p class="text-[10.5px] tabular-nums text-fg-faint">最近 {{ fmtTime(item.latest_at) }}</p>
                  </div>
                  <BaseBadge tone="red">{{ item.count }}</BaseBadge>
                </li>
              </ul>
            </div>

            <div class="rounded-xl border border-line bg-canvas p-3.5">
              <h3 class="text-[12.5px] font-medium text-fg">24h 高频失败账号</h3>
              <p v-if="!monitor.top_failing_actors_24h.length" class="mt-4 py-4 text-center text-[12px] text-fg-faint">
                近 24 小时无异常账号
              </p>
              <ul v-else class="mt-2.5 divide-y divide-line text-[12px]">
                <li
                  v-for="actor in monitor.top_failing_actors_24h"
                  :key="`${actor.actor_email ?? 'anon'}-${actor.latest_action}`"
                  class="flex items-center justify-between gap-2 py-2"
                >
                  <div class="min-w-0">
                    <p class="truncate text-fg">{{ actor.actor_email ?? "匿名 / 未知" }}</p>
                    <p class="truncate font-mono text-[10.5px] text-fg-faint">{{ actor.latest_action }}</p>
                  </div>
                  <BaseBadge tone="amber">{{ actor.count }}</BaseBadge>
                </li>
              </ul>
            </div>

            <div class="rounded-xl border border-line bg-canvas p-3.5">
              <h3 class="text-[12.5px] font-medium text-fg">最近失败消息</h3>
              <p v-if="!monitor.recent_failed_messages.length" class="mt-4 py-4 text-center text-[12px] text-fg-faint">
                最近无失败消息
              </p>
              <ul v-else class="mt-2.5 divide-y divide-line text-[12px]">
                <li
                  v-for="msg in monitor.recent_failed_messages.slice(0, 6)"
                  :key="msg.message_id"
                  class="flex items-center justify-between gap-2 py-2"
                >
                  <div class="min-w-0">
                    <p class="truncate text-fg">{{ msg.user_email }}</p>
                    <p class="truncate text-[10.5px] tabular-nums text-fg-faint">{{ fmtTime(msg.created_at) }}</p>
                  </div>
                  <BaseBadge tone="red">{{ msg.status }}</BaseBadge>
                </li>
              </ul>
            </div>
          </div>
        </template>
      </section>

      <!-- Existing Audit Logs + Membership Plans -->
      <div v-if="data" class="mt-6 grid gap-4 lg:grid-cols-3">
        <section class="overflow-hidden rounded-2xl border border-line bg-canvas lg:col-span-2">
          <div class="flex items-center justify-between border-b border-line px-4 py-3">
            <h2 class="text-[13.5px] font-medium text-fg">最近审计事件</h2>
            <router-link
              :to="{ name: 'audit' }"
              class="focus-ring flex items-center gap-1 rounded-md text-[12px] text-fg-muted transition-colors hover:text-fg"
            >
              查看全部
              <Icon name="chevron-right" :size="13" />
            </router-link>
          </div>

          <table class="w-full text-sm">
            <tbody class="divide-y divide-line">
              <tr v-if="!recent.length">
                <td class="px-4 py-10 text-center text-[13px] text-fg-faint">暂无审计记录</td>
              </tr>
              <tr v-for="row in recent" :key="row.id">
                <td class="whitespace-nowrap px-4 py-2.5 text-[12px] tabular-nums text-fg-faint">
                  {{ fmtTime(row.created_at) }}
                </td>
                <td class="max-w-[180px] truncate px-4 py-2.5 text-[12px] text-fg-muted">
                  {{ row.actor_email ?? "—" }}
                </td>
                <td class="px-4 py-2.5 text-[12px] text-fg">{{ row.action }}</td>
                <td class="px-4 py-2.5 text-right">
                  <BaseBadge :tone="row.outcome === 'success' ? 'green' : 'red'">
                    {{ row.outcome === "success" ? "成功" : "失败" }}
                  </BaseBadge>
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="rounded-2xl border border-line bg-canvas p-4">
          <div class="flex items-center justify-between gap-2">
            <h2 class="text-[13.5px] font-medium text-fg">会员套餐</h2>
            <router-link
              :to="{ name: 'invite-codes' }"
              class="focus-ring flex items-center gap-1 rounded-md text-[12px] text-fg-muted transition-colors hover:text-fg"
            >
              生成邀请码
              <Icon name="chevron-right" :size="13" />
            </router-link>
          </div>
          <div class="mt-3 space-y-2">
            <div v-for="p in data.plans" :key="p.tier" class="rounded-xl border border-line px-3 py-2.5">
              <div class="flex items-center gap-2">
                <BaseBadge :tone="p.tier === 'pro' ? 'brand' : p.tier === 'plus' ? 'blue' : 'gray'">
                  {{ p.label }}
                </BaseBadge>
                <span class="ml-auto text-[11.5px] tabular-nums text-fg">
                  {{ planCredits(p.weekly_credits, p.five_hour_credits) }}
                </span>
              </div>
              <p class="mt-1 text-[11px] text-fg-faint">{{ p.summary }}</p>
            </div>
          </div>
          <div class="mt-4 border-t border-line pt-3">
            <h3 class="text-[12px] font-medium text-fg-muted">会员分布</h3>
            <div class="mt-2 flex h-2 overflow-hidden rounded-full bg-surface">
              <div v-for="d in distribution" :key="d.tier" :class="d.tone" :style="{ width: d.width }" />
            </div>
            <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1">
              <span
                v-for="d in distribution"
                :key="d.tier"
                class="flex items-center gap-1.5 text-[11px] text-fg-muted"
              >
                <span class="h-1.5 w-1.5 rounded-full" :class="d.tone" />
                {{ d.label }} {{ d.count }}
              </span>
            </div>
          </div>
          <p class="mt-4 border-t border-line pt-3 text-[11px] leading-relaxed text-fg-faint">
            1 积分 = {{ numberFormat.format(data.credits_today.tokens_per_credit) }} tokens，额度按用户激活日滚动刷新。
          </p>
        </section>
      </div>
    </template>

    <BaseModal :open="!!stopTarget" title="强制停止运行" width="28rem" @close="stopTarget = null">
      <div v-if="stopTarget" class="space-y-2.5 text-[13px] leading-relaxed text-fg-muted">
        <p>
          确认强制停止
          <span class="font-medium text-fg">{{ stopTarget.user_display_name }}</span>
          （{{ stopTarget.user_email }}）的会话任务？
        </p>
        <div class="rounded-xl border border-line bg-surface/50 px-3 py-2 text-[12px]">
          <p class="font-medium text-fg">{{ stopTarget.title || "未命名会话" }}</p>
          <p class="mt-0.5 font-mono text-[11px] text-fg-faint">Run: {{ stopTarget.active_run_id }}</p>
          <p class="mt-0.5 tabular-nums text-fg-muted">
            已运行 {{ formatDuration(stopTarget.duration_seconds) }}
            <span v-if="stopTarget.is_stalled" class="ml-1 text-danger">· 疑似阻塞</span>
          </p>
        </div>
        <p v-if="stopError" class="rounded-xl bg-danger-weak px-3 py-2 text-[12px] text-danger">{{ stopError }}</p>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="stopTarget = null">取消</BaseButton>
        <BaseButton variant="danger" :loading="stopLoading" @click="confirmForceStop">确认停止</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
