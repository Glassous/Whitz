<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type {
  EvalRunItem,
  ModelPricingResponse,
  QuantEvalsResponse,
  QuantFeedbackOverview,
  QuantModelsTools,
  QuantRetention,
  QuantSummary,
} from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

type DayWindow = 7 | 14 | 30;

const days = ref<DayWindow>(14);
const summary = ref<QuantSummary | null>(null);
const modelsTools = ref<QuantModelsTools | null>(null);
const retention = ref<QuantRetention | null>(null);
const evals = ref<QuantEvalsResponse | null>(null);
const feedback = ref<QuantFeedbackOverview | null>(null);
const pricing = ref<ModelPricingResponse | null>(null);

const loading = ref(false);
const evalRunning = ref(false);
const exporting = ref(false);
const pricingModalOpen = ref(false);
const pricingSaving = ref(false);
const recalculating = ref(false);
const error = ref<string | null>(null);
const toast = ref<string | null>(null);
const hoverIdx = ref<number | null>(null);

const pricingForm = ref({
  model_pattern: "",
  display_name: "",
  input_usd_per_1m: "0.40",
  output_usd_per_1m: "1.50",
});

const numberFormat = new Intl.NumberFormat("zh-CN");

const REACTION_LABEL: Record<string, string> = {
  like: "👍 点赞",
  love: "❤️ 喜欢",
  insightful: "💡 有洞察",
  celebrate: "🎉 太棒了",
  sparkle: "✨ 亮点",
  dislike: "👎 不满意",
};

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
    const [s, mt, ret, ev, fb] = await Promise.all([
      api.get<QuantSummary>(`/admin/quant/summary?days=${days.value}`),
      api.get<QuantModelsTools>(`/admin/quant/models-tools?days=${days.value}`),
      api.get<QuantRetention>(`/admin/quant/retention?days=${Math.max(days.value, 14)}`),
      api.get<QuantEvalsResponse>("/admin/quant/evals"),
      api.get<QuantFeedbackOverview>(`/admin/quant/feedback?days=${days.value}`),
    ]);
    summary.value = s;
    modelsTools.value = mt;
    retention.value = ret;
    evals.value = ev;
    feedback.value = fb;
  } catch (err) {
    error.value = readableError(err);
  } finally {
    loading.value = false;
  }
}

async function triggerEval(dataset: "baseline" | "golden") {
  evalRunning.value = true;
  error.value = null;
  try {
    await api.post<EvalRunItem>(`/admin/quant/evals/run?dataset=${dataset}`, {});
    evals.value = await api.get<QuantEvalsResponse>("/admin/quant/evals");
    showToast(dataset === "golden" ? "Golden 全量评测完成" : "核心基线评测完成");
  } catch (err) {
    error.value = readableError(err);
  } finally {
    evalRunning.value = false;
  }
}

async function exportCsv() {
  exporting.value = true;
  try {
    await api.download(`/admin/quant/export?days=${days.value}`, `whitz-quant-${days.value}d.csv`);
    showToast("量化日报 CSV 已导出");
  } catch (err) {
    error.value = readableError(err);
  } finally {
    exporting.value = false;
  }
}

async function openPricingModal() {
  pricingModalOpen.value = true;
  try {
    pricing.value = await api.get<ModelPricingResponse>("/admin/quant/pricing");
  } catch (err) {
    error.value = readableError(err);
  }
}

async function savePricing() {
  if (!pricingForm.value.model_pattern.trim()) return;
  pricingSaving.value = true;
  try {
    await api.put("/admin/quant/pricing", {
      model_pattern: pricingForm.value.model_pattern.trim(),
      display_name: pricingForm.value.display_name.trim() || pricingForm.value.model_pattern.trim(),
      input_usd_per_1m: Number(pricingForm.value.input_usd_per_1m),
      output_usd_per_1m: Number(pricingForm.value.output_usd_per_1m),
      is_active: true,
    });
    pricingForm.value.model_pattern = "";
    pricingForm.value.display_name = "";
    pricing.value = await api.get<ModelPricingResponse>("/admin/quant/pricing");
    showToast("模型单价已更新");
  } catch (err) {
    error.value = readableError(err);
  } finally {
    pricingSaving.value = false;
  }
}

async function recalculateCosts() {
  recalculating.value = true;
  try {
    const res = await api.post<{ updated_rows: number }>("/admin/quant/pricing/recalculate?days=30", {});
    showToast(`已重算近 30 天遥测成本：更新 ${res.updated_rows} 条记录`);
    await loadAll();
  } catch (err) {
    error.value = readableError(err);
  } finally {
    recalculating.value = false;
  }
}

async function updateFeedbackStatus(id: string, status: "reviewed" | "resolved") {
  try {
    await api.patch(`/admin/quant/feedback/${id}`, { status });
    feedback.value = await api.get<QuantFeedbackOverview>(`/admin/quant/feedback?days=${days.value}`);
  } catch (err) {
    error.value = readableError(err);
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
    ...rows.map((r) => Math.max(r.p95_ms ?? 0, r.p50_ms ?? 0)),
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

function fmtUsd(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return "$0.00";
  return `$${Number(v).toFixed(digits)}`;
}

function cohortCellClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return "text-fg-faint";
  if (pct >= 40) return "bg-success-weak text-success font-medium";
  if (pct >= 15) return "bg-accent-weak text-accent font-medium";
  return "text-fg-muted";
}

onMounted(() => {
  void loadAll();
});
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold tracking-tight text-fg">量化分析与 FinOps 看板</h1>
        <p class="mt-0.5 text-[13px] text-fg-muted">
          延迟分位数、FinOps 模型美元成本与路由节省、用户反馈/点赞质量闭环、D1–D30 留存与回归评测
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
        <BaseButton variant="secondary" size="sm" @click="openPricingModal">模型单价</BaseButton>
        <BaseButton variant="secondary" size="sm" :loading="exporting" @click="exportCsv">导出 CSV</BaseButton>
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

    <!-- 核心量化 & FinOps KPI -->
    <div v-if="summary" class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">P50 / TTFT</p>
        <p class="mt-1 text-lg font-semibold text-fg">{{ fmtMs(summary.latency.p50_ms) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">TTFT: {{ fmtMs(summary.latency.ttft_p50_ms) }}</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">P95 / P99</p>
        <p class="mt-1 text-lg font-semibold text-fg">{{ fmtMs(summary.latency.p95_ms) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">P99: {{ fmtMs(summary.latency.p99_ms) }}</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">Run 成功率</p>
        <p class="mt-1 text-lg font-semibold text-fg">{{ summary.runs.success_rate_pct }}%</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          {{ numberFormat.format(summary.runs.total) }} 次 · 败 {{ summary.runs.failed }}
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">窗口总成本</p>
        <p class="mt-1 text-lg font-semibold text-fg">{{ fmtUsd(summary.finops?.total_cost_usd, 3) }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">单次 {{ fmtUsd(summary.finops?.avg_cost_per_run_usd, 4) }}</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">智能路由节省</p>
        <p class="mt-1 text-lg font-semibold text-success">
          {{ summary.finops?.routing_savings_pct ?? 0 }}%
        </p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          省 {{ fmtUsd(summary.finops?.routing_savings_usd, 3) }}
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">CSAT 好评率</p>
        <p class="mt-1 text-lg font-semibold text-fg">
          {{ summary.quality?.csat_pct !== null && summary.quality?.csat_pct !== undefined ? `${summary.quality.csat_pct}%` : "—" }}
        </p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          评价 {{ summary.quality?.user_reactions_total ?? 0 }} · AI赞 {{ summary.quality?.ai_positive_reactions ?? 0 }}
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">重生成率</p>
        <p class="mt-1 text-lg font-semibold text-fg">{{ summary.quality?.regenerate_rate_pct ?? 0 }}%</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">工具误率 {{ summary.quality?.tool_error_rate_pct ?? 0 }}%</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">DAU / MAU 粘性</p>
        <p class="mt-1 text-lg font-semibold text-fg">
          {{ retention?.stickiness ? `${retention.stickiness.dau_mau_pct}%` : "—" }}
        </p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          {{ retention?.stickiness ? `${retention.stickiness.dau}/${retention.stickiness.mau}` : "暂无数据" }}
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
          P95: {{ fmtMs(latencyChart.rows[hoverIdx].p95_ms) }} ·
          成本: {{ fmtUsd(latencyChart.rows[hoverIdx].cost_usd, 4) }}
        </div>
      </div>

      <!-- 模型路由分布 & 会员档位单位经济 -->
      <div class="rounded-2xl border border-line bg-surface p-5 space-y-5">
        <div>
          <h2 class="mb-3 text-[14px] font-semibold text-fg">模型路由效能分布</h2>
          <div v-if="!modelsTools?.routes.length" class="py-4 text-center text-[13px] text-fg-faint">
            暂无路由遥测数据
          </div>
          <div v-else class="space-y-3">
            <div v-for="rt in modelsTools.routes" :key="rt.route" class="space-y-1">
              <div class="flex items-center justify-between text-[12px]">
                <span class="font-medium text-fg">{{ rt.route }}</span>
                <span class="text-fg-muted">
                  {{ rt.runs }}次 ({{ rt.share_pct }}%) · {{ fmtUsd(rt.cost_usd, 3) }}
                </span>
              </div>
              <div class="h-1.5 overflow-hidden rounded-full bg-hover">
                <div class="h-full rounded-full bg-accent" :style="{ width: `${rt.share_pct}%` }" />
              </div>
            </div>
          </div>
        </div>

        <div v-if="modelsTools?.tier_economics?.length" class="border-t border-line pt-4">
          <h3 class="mb-2 text-[13px] font-semibold text-fg">会员档位单位成本 (ARPC)</h3>
          <div class="space-y-1.5 text-[12px]">
            <div v-for="te in modelsTools.tier_economics" :key="te.tier" class="flex items-center justify-between">
              <span class="uppercase font-medium text-fg">{{ te.tier }}</span>
              <span class="text-fg-muted">
                {{ te.active_users }} 人 · 总 {{ fmtUsd(te.cost_usd, 3) }} · 人均 {{ fmtUsd(te.avg_cost_per_user_usd, 4) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 工具效能排行 & 消息表情 / 用户设置反馈 -->
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

      <!-- 消息评价与设置页产品反馈 -->
      <div class="rounded-2xl border border-line bg-surface p-5 space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-[14px] font-semibold text-fg">消息评价分布 & 产品反馈</h2>
          <span v-if="feedback?.product_feedback.avg_rating" class="text-[12.5px] font-medium text-fg">
            设置页均分 {{ feedback.product_feedback.avg_rating }} / 5.0
          </span>
        </div>

        <div v-if="feedback" class="grid grid-cols-2 gap-3 text-[12px]">
          <div class="rounded-xl border border-line bg-canvas p-3">
            <p class="mb-1.5 font-medium text-fg">用户消息评价 ({{ feedback.reactions.user_total }})</p>
            <div v-if="!feedback.reactions.user_total" class="text-fg-faint">暂无评价</div>
            <div v-else class="space-y-1">
              <div v-for="(cnt, key) in feedback.reactions.user_breakdown" :key="key" class="flex justify-between">
                <span>{{ REACTION_LABEL[key] || key }}</span>
                <span class="font-medium text-fg">{{ cnt }}</span>
              </div>
            </div>
          </div>
          <div class="rounded-xl border border-line bg-canvas p-3">
            <p class="mb-1.5 font-medium text-fg">AI 正向点赞 ({{ feedback.reactions.ai_total }})</p>
            <div v-if="!feedback.reactions.ai_total" class="text-fg-faint">暂无点赞</div>
            <div v-else class="space-y-1">
              <div v-for="(cnt, key) in feedback.reactions.ai_breakdown" :key="key" class="flex justify-between">
                <span>{{ REACTION_LABEL[key] || key }}</span>
                <span class="font-medium text-fg">{{ cnt }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="feedback?.product_feedback.items.length" class="space-y-2">
          <p class="text-[12px] font-medium text-fg-muted">最近设置页反馈</p>
          <div
            v-for="item in feedback.product_feedback.items.slice(0, 4)"
            :key="item.id"
            class="rounded-xl border border-line bg-canvas p-3 text-[12px]"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium text-fg">{{ item.user_email }} · {{ item.rating }}/5 · {{ item.category }}</span>
              <div class="flex items-center gap-1.5">
                <BaseBadge :tone="item.status === 'resolved' ? 'green' : item.status === 'reviewed' ? 'blue' : 'gray'">
                  {{ item.status }}
                </BaseBadge>
                <button
                  v-if="item.status === 'new'"
                  type="button"
                  class="text-[11px] text-accent hover:underline"
                  @click="updateFeedbackStatus(item.id, 'reviewed')"
                >
                  标记已读
                </button>
                <button
                  v-if="item.status !== 'resolved'"
                  type="button"
                  class="text-[11px] text-success hover:underline"
                  @click="updateFeedbackStatus(item.id, 'resolved')"
                >
                  解决
                </button>
              </div>
            </div>
            <p class="mt-1 line-clamp-2 text-fg-muted">{{ item.content }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 转化漏斗与 D1-D30 留存热力矩阵 -->
    <div class="grid gap-4 lg:grid-cols-3">
      <div class="rounded-2xl border border-line bg-surface p-5">
        <h2 class="mb-3 text-[14px] font-semibold text-fg">用户转化漏斗</h2>
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

      <div class="rounded-2xl border border-line bg-surface p-5 lg:col-span-2">
        <h2 class="mb-3 text-[14px] font-semibold text-fg">Cohort 留存热力矩阵 (D1 / D3 / D7 / D14 / D30)</h2>
        <div v-if="!retention?.cohorts.length" class="py-8 text-center text-[13px] text-fg-faint">暂无队列数据</div>
        <div v-else class="max-h-64 overflow-auto">
          <table class="w-full text-left text-[12px]">
            <thead>
              <tr class="border-b border-line text-fg-muted">
                <th class="pb-2 font-medium">队列日期</th>
                <th class="pb-2 text-right font-medium">新用户</th>
                <th class="pb-2 text-right font-medium">D1</th>
                <th class="pb-2 text-right font-medium">D3</th>
                <th class="pb-2 text-right font-medium">D7</th>
                <th class="pb-2 text-right font-medium">D14</th>
                <th class="pb-2 text-right font-medium">D30</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="c in retention.cohorts.slice(-10).reverse()" :key="c.cohort_day">
                <td class="py-1.5 font-mono text-fg">{{ c.cohort_day }}</td>
                <td class="py-1.5 text-right text-fg-muted">{{ c.new_users }}</td>
                <td class="py-1.5 text-right rounded px-1" :class="cohortCellClass(c.d1_pct)">
                  {{ c.d1_pct !== null ? `${c.d1_pct}%` : "—" }}
                </td>
                <td class="py-1.5 text-right rounded px-1" :class="cohortCellClass(c.d3_pct)">
                  {{ c.d3_pct !== null ? `${c.d3_pct}%` : "—" }}
                </td>
                <td class="py-1.5 text-right rounded px-1" :class="cohortCellClass(c.d7_pct)">
                  {{ c.d7_pct !== null ? `${c.d7_pct}%` : "—" }}
                </td>
                <td class="py-1.5 text-right rounded px-1" :class="cohortCellClass(c.d14_pct)">
                  {{ c.d14_pct !== null && c.d14_pct !== undefined ? `${c.d14_pct}%` : "—" }}
                </td>
                <td class="py-1.5 text-right rounded px-1" :class="cohortCellClass(c.d30_pct)">
                  {{ c.d30_pct !== null && c.d30_pct !== undefined ? `${c.d30_pct}%` : "—" }}
                </td>
              </tr>
            </tbody>
          </table>
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
        <div class="flex items-center gap-2">
          <BaseButton size="sm" variant="secondary" :loading="evalRunning" @click="triggerEval('baseline')">
            运行核心基线
          </BaseButton>
          <BaseButton size="sm" :loading="evalRunning" @click="triggerEval('golden')">
            <Icon name="activity" :size="14" />
            运行 Golden 数据集
          </BaseButton>
        </div>
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

    <!-- 模型单价配置 Modal -->
    <BaseModal :open="pricingModalOpen" title="模型 FinOps 单价配置 (USD / 1M Tokens)" width="42rem" @close="pricingModalOpen = false">
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <BaseInput v-model="pricingForm.model_pattern" label="模型名/前缀" placeholder="如 deepseek-chat" />
          <BaseInput v-model="pricingForm.display_name" label="展示名称" placeholder="DeepSeek V3" />
          <BaseInput v-model="pricingForm.input_usd_per_1m" label="输入 ($/1M)" type="number" />
          <BaseInput v-model="pricingForm.output_usd_per_1m" label="输出 ($/1M)" type="number" />
        </div>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <BaseButton size="sm" variant="secondary" :loading="recalculating" @click="recalculateCosts">
            按最新单价重算近 30 天成本
          </BaseButton>
          <BaseButton size="sm" :loading="pricingSaving" @click="savePricing">保存自定义单价</BaseButton>
        </div>

        <div v-if="pricing?.custom.length">
          <p class="mb-1.5 text-[12px] font-medium text-fg-muted">自定义单价覆盖</p>
          <div class="space-y-1 text-[12px]">
            <div v-for="c in pricing.custom" :key="c.id" class="flex justify-between rounded-lg bg-surface px-3 py-1.5">
              <span class="font-mono text-fg">{{ c.model_pattern }} ({{ c.display_name }})</span>
              <span class="text-fg-muted">In ${{ c.input_usd_per_1m }} / Out ${{ c.output_usd_per_1m }}</span>
            </div>
          </div>
        </div>

        <div v-if="pricing?.defaults.length">
          <p class="mb-1.5 text-[12px] font-medium text-fg-muted">系统默认兜底费率</p>
          <div class="max-h-40 overflow-auto space-y-1 text-[12px]">
            <div v-for="d in pricing.defaults" :key="d.model_pattern" class="flex justify-between rounded-lg bg-surface px-3 py-1">
              <span class="font-mono text-fg">{{ d.model_pattern }}</span>
              <span class="text-fg-muted">In ${{ d.input_usd_per_1m }} / Out ${{ d.output_usd_per_1m }}</span>
            </div>
          </div>
        </div>
      </div>
    </BaseModal>
  </div>
</template>
