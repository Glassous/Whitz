<script setup lang="ts">
import { computed, ref } from "vue";

export interface DailyChartPoint {
  day: string;
  total: number;
  succeeded: number;
  failed: number;
  success_rate_pct: number | null;
  extraLabel?: string;
}

const props = withDefaults(
  defineProps<{
    title: string;
    subtitle?: string;
    rows: DailyChartPoint[];
    successLabel?: string;
    failLabel?: string;
  }>(),
  {
    subtitle: "",
    successLabel: "成功",
    failLabel: "失败",
  },
);

const hoverIdx = ref<number | null>(null);

const CHART_W = 680;
const CHART_H = 210;
const PAD_L = 42;
const PAD_R = 40;
const PAD_T = 14;
const PAD_B = 26;
const PLOT_W = CHART_W - PAD_L - PAD_R;
const PLOT_H = CHART_H - PAD_T - PAD_B;

function niceMax(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 4;
  if (raw <= 4) return 4;
  if (raw <= 10) return 10;
  const exp = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / exp;
  const nice = norm <= 1.5 ? 1.5 : norm <= 2 ? 2 : norm <= 4 ? 4 : norm <= 6 ? 6 : norm <= 8 ? 8 : 10;
  return Math.ceil(nice * exp);
}

const chart = computed(() => {
  const list = props.rows ?? [];
  const maxTotal = niceMax(Math.max(0, ...list.map((r) => r.total)));
  const n = Math.max(1, list.length);
  const slotW = PLOT_W / n;
  const barW = Math.max(5, Math.min(22, slotW * 0.54));

  const items = list.map((r, i) => {
    const cx = PAD_L + slotW * (i + 0.5);
    const barX = cx - barW / 2;
    const succH = (Math.max(0, r.succeeded) / maxTotal) * PLOT_H;
    const failH = (Math.max(0, r.failed) / maxTotal) * PLOT_H;
    const succY = PAD_T + PLOT_H - succH;
    const failY = succY - failH;
    const rateY =
      r.success_rate_pct !== null
        ? PAD_T + PLOT_H - (Math.max(0, Math.min(100, r.success_rate_pct)) / 100) * PLOT_H
        : null;
    return {
      ...r,
      index: i,
      cx,
      barX,
      slotX: PAD_L + i * slotW,
      slotW,
      succH,
      succY,
      failH,
      failY,
      rateY,
    };
  });

  const ratePoints = items
    .filter((it) => it.rateY !== null)
    .map((it) => `${it.cx.toFixed(1)},${(it.rateY as number).toFixed(1)}`)
    .join(" ");

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => ({
    y: PAD_T + PLOT_H - t * PLOT_H,
    leftLabel: String(Math.round(maxTotal * t)),
    rightLabel: `${Math.round(t * 100)}%`,
  }));

  return { items, barW, ratePoints, ticks };
});

const hovered = computed(() => {
  if (hoverIdx.value === null) return null;
  return chart.value.items[hoverIdx.value] ?? null;
});
</script>

<template>
  <div class="rounded-2xl border border-line bg-surface p-5">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 class="text-[14px] font-semibold text-fg">{{ title }}</h3>
        <p v-if="subtitle" class="text-[12px] text-fg-muted">{{ subtitle }}</p>
      </div>
      <div class="flex items-center gap-3 text-[11.5px] text-fg-muted">
        <span class="flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-sm bg-success" /> {{ successLabel }}
        </span>
        <span class="flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-sm bg-danger" /> {{ failLabel }}
        </span>
        <span class="flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-accent" /> 成功率
        </span>
      </div>
    </div>

    <div v-if="!rows.length" class="py-10 text-center text-[13px] text-fg-faint">暂无趋势数据</div>
    <template v-else>
      <svg :viewBox="`0 0 ${CHART_W} ${CHART_H}`" class="w-full overflow-visible">
        <g v-for="t in chart.ticks" :key="t.rightLabel">
          <line
            :x1="PAD_L"
            :x2="CHART_W - PAD_R"
            :y1="t.y"
            :y2="t.y"
            stroke="currentColor"
            class="text-line"
            stroke-dasharray="3 3"
          />
          <text :x="PAD_L - 6" :y="t.y + 3" text-anchor="end" class="fill-fg-faint text-[10px]">
            {{ t.leftLabel }}
          </text>
          <text :x="CHART_W - PAD_R + 6" :y="t.y + 3" text-anchor="start" class="fill-fg-faint text-[10px]">
            {{ t.rightLabel }}
          </text>
        </g>

        <g v-for="it in chart.items" :key="it.day">
          <rect
            v-if="hoverIdx === it.index"
            :x="it.slotX"
            :y="PAD_T"
            :width="it.slotW"
            :height="PLOT_H"
            fill="currentColor"
            class="text-hover"
            opacity="0.6"
          />
          <rect
            v-if="it.succH > 0"
            :x="it.barX"
            :y="it.succY"
            :width="chart.barW"
            :height="it.succH"
            rx="2"
            fill="var(--success)"
            opacity="0.82"
          />
          <rect
            v-if="it.failH > 0"
            :x="it.barX"
            :y="it.failY"
            :width="chart.barW"
            :height="it.failH"
            rx="2"
            fill="var(--danger)"
            opacity="0.88"
          />
          <rect
            :x="it.slotX"
            :y="PAD_T"
            :width="it.slotW"
            :height="PLOT_H"
            fill="transparent"
            @mouseenter="hoverIdx = it.index"
            @mouseleave="hoverIdx = null"
          />
          <text
            v-if="
              it.index === 0 ||
              it.index === chart.items.length - 1 ||
              it.index % Math.max(1, Math.ceil(chart.items.length / 6)) === 0
            "
            :x="it.cx"
            :y="CHART_H - 6"
            text-anchor="middle"
            class="fill-fg-faint text-[10px]"
          >
            {{ it.day.slice(5) }}
          </text>
        </g>

        <polyline
          v-if="chart.ratePoints"
          fill="none"
          stroke="var(--accent)"
          stroke-width="2"
          stroke-linejoin="round"
          stroke-linecap="round"
          :points="chart.ratePoints"
        />

        <g v-for="it in chart.items" :key="`dot-${it.day}`">
          <circle
            v-if="it.rateY !== null"
            :cx="it.cx"
            :cy="it.rateY"
            :r="hoverIdx === it.index ? 4 : 2.3"
            fill="var(--accent)"
          />
        </g>
      </svg>

      <div class="mt-2 min-h-[18px] text-[12px] text-fg-muted">
        <template v-if="hovered">
          <span class="font-medium text-fg">{{ hovered.day }}</span>
          · 总计 {{ hovered.total }} · {{ successLabel }} {{ hovered.succeeded }} · {{ failLabel }} {{ hovered.failed }}
          · 成功率 {{ hovered.success_rate_pct !== null ? `${hovered.success_rate_pct}%` : "—" }}
          <span v-if="hovered.extraLabel"> · {{ hovered.extraLabel }}</span>
        </template>
        <span v-else class="text-fg-faint">悬停柱状图可查看每日明细与成功率</span>
      </div>
    </template>
  </div>
</template>
