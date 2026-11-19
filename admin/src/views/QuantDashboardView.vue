<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type {
  EvalRunItem,
  QuantEvalsResponse,
  QuantModelsTools,
  QuantRetention,
  QuantSummary,
} from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import Icon from "../components/ui/Icon.vue";

type DayWindow = 7 | 14 | 30;

const days = ref<DayWindow>(14);
const summary = ref<QuantSummary | null>(null);
const modelsTools = ref<QuantModelsTools | null>(null);
const retention = ref<QuantRetention | null>(null);
const evals = ref<QuantEvalsResponse | null>(null);

const loading = ref(false);
const evalRunning = ref(false);
const error = ref<string | null>(null);
const hoverIdx = ref<number | null>(null);

const numberFormat = new Intl.NumberFormat("zh-CN");

async function loadAll() {
  loading.value = true;
  error.value = null;
  try {
    const [s, mt, ret, ev] = await Promise.all([
      api.get<QuantSummary>(`/admin/quant/summary?days=${days.value}`),
      api.get<QuantModelsTools>(`/admin/quant/models-tools?days=${days.value}`),
      api.get<QuantRetention>(`/admin/quant/retention?days=${Math.max(days.value, 14)}`),
      api.get<QuantEvalsResponse>("/admin/quant/evals"),
    ]);
    summary.value = s;
    modelsTools.value = mt;
    retention.value = ret;
    evals.value = ev;
  } catch (err) {
    error.value = readableError(err);
  } finally {
    loading.value = false;
  }
}

async function triggerEval() {
  evalRunning.value = true;
  error.value = null;
  try {
    await api.post<EvalRunItem>("/admin/quant/evals/run", {});
    evals.value = await api.get<QuantEvalsResponse>("/admin/quant/evals");
  } catch (err) {
    error.value = readableError(err);
  } finally {
    evalRunning.value = false;
  }
}

function selectDays(d: DayWindow) {
  if (days.value === d) return;
  days.value = d;
  void loadAll();
}

const CHART_W = 680;
const CHART_H = 210;
const PAD_L = 48;
const PAD_R = 16;
const PAD_T = 14;
const PAD_B = 26;
const PLOT_W = CHART_W - PAD_L - PAD_R;
const PLOT_H = CHART_H - PAD_T - PAD_B;

const latencyChart = computed(() => {
  const rows = summary.value?.daily_latency ?? [];
  const maxVal = Math.max(
    100,
    ...rows.map((r) => Math.max(r.p95_ms ?? 0, r.p50_ms ?? 0))
  );
  const nice = Math.ceil(maxVal / 100) * 100;
  const n = Math.max(1, rows.length);
  const xFor = (i: number) => (n === 1 ? PAD_L + PLOT_W / 2 : PAD_L + (i / (n - 1)) * PLOT_W);
  const yFor = (v: number) => PAD_T + PLOT_H - (v / nice) * PLOT_H;

  const p50Points = rows
    .map((r, i) => (r.p50_ms !== null ? `${xFor(i).toFixed(1)},${yFor(r.p50_ms).toFixed(1)}` : null))
    .filter((p): p is string => p !== null)
    .join(" ");
  const p95Points = rows
    .map((r, i) => (r.p95_ms !== null ? `${xFor(i).toFixed(1)},${yFor(r.p95_ms).toFixed(1)}` : null))
    .filter((p): p is string => p !== null)
    .join(" ");

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => ({
    y: PAD_T + PLOT_H - t * PLOT_H,
    label: `${Math.round(nice * t)}ms`,
  }));

  return { rows, p50Points, p95Points, ticks, xFor, yFor };
});

function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${Math.round(v)} ms`;
}

onMounted(() => {
  void loadAll();
});
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight text-fg">量化分析看板</h1>
        <p class="mt-0.5 text-[13px] text-fg-muted">
          延迟分位数 (P50/P95/P99)、模型路由效能、用户留存漏斗与 Agent 评测量化基线
        </p>
      </div>
      <div class="flex items-center gap-2">
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
        <BaseButton variant="secondary" size="sm" :loading="loading" @click="loadAll">
          <Icon name="refresh" :size="14" />
          刷新
        </BaseButton>
      </div>
    </div>

    <div v-if="error" class="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-[13px] text-danger">
      {{ error }}
    </div>

    <!-- 核心量化 KPI -->
    <div v-if="summary" class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">P50 延迟</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ fmtMs(summary.latency.p50_ms) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">TTFT P50: {{ fmtMs(summary.latency.ttft_p50_ms) }}</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">P95 / P99 延迟</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ fmtMs(summary.latency.p95_ms) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">P99: {{ fmtMs(summary.latency.p99_ms) }}</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">Run 成功率</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ summary.runs.success_rate_pct }}%</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          总 {{ numberFormat.format(summary.runs.total) }} · 失败 {{ summary.runs.failed }}
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">单次均耗 Token</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ numberFormat.format(summary.runs.avg_tokens_per_run) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">Prompt 占比 {{ summary.runs.prompt_ratio_pct }}%</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">窗口总 Token</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ numberFormat.format(summary.runs.total_tokens) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">≈ {{ summary.runs.total_credits }} 积分</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">最新评测通过率</p>
        <p class="mt-1 text-xl font-semibold text-fg">
          {{ evals?.latest ? `${(evals.latest.pass_rate * 100).toFixed(1)}%` : "—" }}
        </p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          {{ evals?.pass_rate_delta_pct !== null && evals?.pass_rate_delta_pct !== undefined
            ? `较上次 ${evals.pass_rate_delta_pct >= 0 ? "+" : ""}${evals.pass_rate_delta_pct}%`
            : "暂无基线对比" }}
        </p>
      </div>
    </div>

    <!-- P50 / P95 延迟趋势图 + 路由分布 -->
    <div class="grid gap-4 lg:grid-cols-3">
      <div class="rounded-2xl border border-line bg-surface p-5 lg:col-span-2">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-[14px] font-semibold text-fg">每日响应延迟分位趋势 (P50 vs P95)</h2>
          <div class="flex items-center gap-3 text-[11.5px] text-fg-muted">
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full bg-accent" /> P50</span>
            <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full bg-[#7C6BF0]" /> P95</span>
          </div>
        </div>
        <svg :viewBox="`0 0 ${CHART_W} ${CHART_H}`" class="w-full overflow-visible">
          <g v-for="t in latencyChart.ticks" :key="t.label">
            <line :x1="PAD_L" :x2="CHART_W - PAD_R" :y1="t.y" :y2="t.y" stroke="currentColor" class="text-line" stroke-dasharray="3 3" />
            <text :x="PAD_L - 6" :y="t.y + 3" text-anchor="end" class="fill-fg-faint text-[10px]">{{ t.label }}</text>
          </g>
          <polyline
            v-if="latencyChart.p95Points"
            fill="none"
            stroke="#7C6BF0"
            stroke-width="2"
            stroke-linejoin="round"
            :points="latencyChart.p95Points"
          />
          <polyline
            v-if="latencyChart.p50Points"
            fill="none"
            stroke="var(--accent)"
            stroke-width="2"
            stroke-linejoin="round"
            :points="latencyChart.p50Points"
          />
          <g v-for="(r, i) in latencyChart.rows" :key="r.day">
            <rect
              :x="latencyChart.xFor(i) - 10"
              :y="PAD_T"
              width="20"
              :height="PLOT_H"
              fill="transparent"
              @mouseenter="hoverIdx = i"
              @mouseleave="hoverIdx = null"
            />
            <circle
              v-if="r.p50_ms !== null && hoverIdx === i"
              :cx="latencyChart.xFor(i)"
              :cy="latencyChart.yFor(r.p50_ms)"
              r="3.5"
              fill="var(--accent)"
            />
            <circle
              v-if="r.p95_ms !== null && hoverIdx === i"
              :cx="latencyChart.xFor(i)"
              :cy="latencyChart.yFor(r.p95_ms)"
              r="3.5"
              fill="#7C6BF0"
            />
            <text
              v-if="i === 0 || i === latencyChart.rows.length - 1 || i % Math.ceil(latencyChart.rows.length / 5) === 0"
              :x="latencyChart.xFor(i)"
              :y="CHART_H - 6"
              text-anchor="middle"
              class="fill-fg-faint text-[10px]"
            >
              {{ r.day.slice(5) }}
            </text>
          </g>
        </svg>
        <div v-if="hoverIdx !== null && latencyChart.rows[hoverIdx]" class="mt-1 text-[12px] text-fg-muted">
          {{ latencyChart.rows[hoverIdx].day }} · 运行 {{ latencyChart.rows[hoverIdx].runs }} 次 ·
          P50: {{ fmtMs(latencyChart.rows[hoverIdx].p50_ms) }} ·
          P95: {{ fmtMs(latencyChart.rows[hoverIdx].p95_ms) }}
        </div>
      </div>

      <!-- 模型路由分布 -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <h2 class="mb-3 text-[14px] font-semibold text-fg">模型路由分布</h2>
        <div v-if="!modelsTools?.routes.length" class="py-10 text-center text-[13px] text-fg-faint">
          暂无路由遥测数据
        </div>
        <div v-else class="space-y-3">
          <div v-for="rt in modelsTools.routes" :key="rt.route" class="space-y-1">
            <div class="flex items-center justify-between text-[12.5px]">
              <span class="font-medium text-fg">{{ rt.route }}</span>
              <span class="text-fg-muted">{{ rt.runs }} 次 ({{ rt.share_pct }}%) · P95 {{ fmtMs(rt.p95_ms) }}</span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-hover">
              <div class="h-full rounded-full bg-accent" :style="{ width: `${rt.share_pct}%` }" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 工具效能排行 & 转化漏斗 -->
    <div class="grid gap-4 lg:grid-cols-2">
      <div class="rounded-2xl border border-line bg-surface p-5">
        <h2 class="mb-3 text-[14px] font-semibold text-fg">Top 工具调用与耗时排行</h2>
        <div v-if="!modelsTools?.tools.length" class="py-8 text-center text-[13px] text-fg-faint">
          暂无工具调用遥测
        </div>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-[12.5px]">
            <thead>
              <tr class="border-b border-line text-fg-muted">
                <th class="pb-2 font-medium">工具名</th>
                <th class="pb-2 text-right font-medium">调用</th>
                <th class="pb-2 text-right font-medium">错误率</th>
                <th class="pb-2 text-right font-medium">平均耗时</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="t in modelsTools.tools" :key="t.name">
                <td class="py-2 font-mono text-fg">{{ t.name }}</td>
                <td class="py-2 text-right text-fg-muted">{{ t.calls }}</td>
                <td class="py-2 text-right" :class="t.error_rate_pct > 5 ? 'text-danger' : 'text-fg-muted'">
                  {{ t.error_rate_pct }}%
                </td>
                <td class="py-2 text-right text-fg-muted">{{ t.avg_duration_ms }} ms</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 转化漏斗 -->
      <div class="rounded-2xl border border-line bg-surface p-5">
        <h2 class="mb-3 text-[14px] font-semibold text-fg">用户转化漏斗与留存</h2>
        <div v-if="retention?.funnel.length" class="space-y-3">
          <div v-for="step in retention.funnel" :key="step.stage" class="space-y-1">
            <div class="flex justify-between text-[12.5px]">
              <span class="text-fg">{{ step.stage }}</span>
              <span class="font-medium text-fg">{{ numberFormat.format(step.count) }} ({{ step.pct }}%)</span>
            </div>
            <div class="h-2 overflow-hidden rounded-full bg-hover">
              <div class="h-full rounded-full bg-[#7C6BF0]" :style="{ width: `${step.pct}%` }" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Agent 评测量化基线 -->
    <div class="rounded-2xl border border-line bg-surface p-5">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 class="text-[14px] font-semibold text-fg">Agent 评测量化基线 (Evals)</h2>
          <p class="text-[12px] text-fg-muted">路由准确性、工具调用与 HITL 安全门控回归基线</p>
        </div>
        <BaseButton size="sm" :loading="evalRunning" @click="triggerEval">
          <Icon name="activity" :size="14" />
          运行基线评测 (Dry-Run)
        </BaseButton>
      </div>

      <div v-if="!evals?.items.length" class="py-6 text-center text-[13px] text-fg-faint">
        暂无评测记录，点击右上角运行首次基线评测
      </div>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-left text-[12.5px]">
          <thead>
            <tr class="border-b border-line text-fg-muted">
              <th class="pb-2 font-medium">数据集</th>
              <th class="pb-2 font-medium">模式</th>
              <th class="pb-2 text-right font-medium">通过 / 总数</th>
              <th class="pb-2 text-right font-medium">通过率</th>
              <th class="pb-2 font-medium">触发人</th>
              <th class="pb-2 text-right font-medium">时间</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-line">
            <tr v-for="ev in evals.items" :key="ev.id">
              <td class="py-2 font-medium text-fg">{{ ev.dataset_name }}</td>
              <td class="py-2"><BaseBadge tone="gray">{{ ev.mode }}</BaseBadge></td>
              <td class="py-2 text-right text-fg-muted">{{ ev.passed }} / {{ ev.total }}</td>
              <td class="py-2 text-right font-semibold" :class="ev.pass_rate >= 0.9 ? 'text-success' : 'text-warning'">
                {{ (ev.pass_rate * 100).toFixed(1) }}%
              </td>
              <td class="py-2 text-fg-muted">{{ ev.triggered_by || "system" }}</td>
              <td class="py-2 text-right text-fg-faint">{{ new Date(ev.created_at).toLocaleString("zh-CN") }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
