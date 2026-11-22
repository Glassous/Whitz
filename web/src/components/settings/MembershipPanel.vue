<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useAuthStore } from "../../stores/auth";
import { useCreditsStore } from "../../stores/credits";
import BaseButton from "../ui/BaseButton.vue";
import type { MembershipPlan, MembershipTier } from "../../types";

const auth = useAuthStore();
const credits = useCreditsStore();

const redeemCode = ref("");
const redeemMsg = ref<string | null>(null);
const redeemErr = ref<string | null>(null);
const redeeming = ref(false);
const redeemInput = ref<HTMLInputElement | null>(null);

const fallbackPlans: MembershipPlan[] = [
  {
    tier: "free",
    label: "Free",
    weekly_credits: 100,
    five_hour_credits: 20,
    max_runs_per_user: 1,
    chat_per_minute: 10,
    run_max_seconds: 600,
    max_tool_iterations: 30,
    summary: "每周 100 积分，5 小时最多 20 积分",
  },
  {
    tier: "plus",
    label: "Plus",
    weekly_credits: 1500,
    five_hour_credits: 300,
    max_runs_per_user: 1,
    chat_per_minute: 20,
    run_max_seconds: 900,
    max_tool_iterations: 60,
    summary: "每周 1500 积分，5 小时最多 300 积分",
  },
  {
    tier: "pro",
    label: "Pro",
    weekly_credits: 25000,
    five_hour_credits: null,
    max_runs_per_user: 2,
    chat_per_minute: 30,
    run_max_seconds: 1200,
    max_tool_iterations: 200,
    summary: "每周 25000 积分，无 5 小时限制",
  },
];

const displayPlans = computed<MembershipPlan[]>(() =>
  credits.status?.plans?.length ? credits.status.plans : fallbackPlans,
);

const tierBadgeClass = computed(() => {
  if (credits.tier === "pro") return "bg-primary text-primary-fg";
  if (credits.tier === "plus") return "bg-active text-fg";
  return "bg-surface text-fg-muted";
});

function fmtDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "长期有效";
}

function fmtReset(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

const availablePercent = computed(() => {
  const current = credits.status;
  if (!current) return null;
  if (current.tier === "pro") return credits.weeklyPercent;
  return Math.min(credits.weeklyPercent, credits.fiveHourPercent);
});

function progressClass(percent: number): string {
  if (percent <= 15) return "bg-danger";
  if (percent <= 35) return "bg-warning";
  return "bg-accent";
}

function planTagline(tier: MembershipTier): string {
  if (tier === "pro") return "无 5 小时限制 · 可单次用完整周额度";
  if (tier === "plus") return "更高周额度 · 5 小时分段恢复";
  return "基础周额度 · 5 小时分段恢复";
}

async function redeem() {
  redeemMsg.value = null;
  redeemErr.value = null;
  if (!redeemCode.value.trim()) {
    redeemErr.value = "请输入邀请码";
    redeemInput.value?.focus();
    return;
  }
  redeeming.value = true;
  try {
    const info = await credits.redeem(redeemCode.value);
    redeemCode.value = "";
    redeemMsg.value = `已升级至 ${info.tier_label}（至 ${fmtDate(info.expires_at)}）`;
    await auth.refreshUser();
  } catch (e: any) {
    redeemErr.value =
      typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "兑换失败，请检查邀请码");
    redeemInput.value?.focus();
  } finally {
    redeeming.value = false;
  }
}

onMounted(() => {
  void credits.fetch();
});
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-3">
    <!-- Section header -->
    <div class="flex items-center justify-between gap-2">
      <h2 id="heading-membership" class="text-[15px] font-semibold text-fg">会员与额度</h2>
      <span class="text-[12px] tabular-nums text-fg-faint">
        {{ credits.tier === "free" ? "滚动窗口刷新" : `有效至 ${fmtDate(credits.status?.expires_at ?? null)}` }}
      </span>
    </div>

    <!-- Current tier & available quota summary -->
    <div class="flex items-center justify-between gap-3 rounded-2xl bg-canvas px-3.5 py-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <span
            class="shrink-0 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold leading-snug"
            :class="tierBadgeClass"
          >
            {{ credits.tierLabel }}
          </span>
          <span v-if="credits.overdrawn" class="text-[12px] font-medium text-danger">额度已用尽</span>
        </div>
        <p class="mt-1 truncate text-[12.5px] text-fg-muted">
          {{ credits.status?.plan?.summary || planTagline(credits.tier) }}
        </p>
      </div>

      <div class="shrink-0 text-right">
        <p class="text-[11.5px] text-fg-faint">当前可用</p>
        <p class="mt-0.5 text-[21px] font-semibold leading-none tabular-nums text-fg">
          {{ availablePercent === null ? "—" : `${availablePercent}%` }}
        </p>
      </div>
    </div>

    <div
      v-if="credits.overdrawn"
      role="alert"
      class="rounded-xl bg-danger-weak px-3 py-2 text-[12.5px] text-danger"
    >
      额度已耗尽，将于 {{ fmtReset(credits.nextResetAt) }} 重置后恢复。
    </div>

    <div
      v-if="credits.error"
      role="alert"
      class="rounded-xl bg-danger-weak px-3 py-2 text-[12.5px] text-danger"
    >
      {{ credits.error }}
    </div>

    <!-- Quota windows (hide 5-hour block entirely for Pro) -->
    <div
      class="grid gap-2.5"
      :class="credits.tier === 'pro' ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2'"
    >
      <div class="rounded-2xl bg-canvas/75 p-3 dark:bg-canvas/80">
        <div class="flex items-center justify-between text-[12.5px]">
          <span class="font-medium text-fg-muted">本周剩余</span>
          <span class="font-semibold tabular-nums text-fg">
            {{ !credits.status ? "—" : credits.status.weekly.limit ? `${credits.weeklyPercent}%` : "不限" }}
          </span>
        </div>
        <div class="mt-2 h-1.5 overflow-clip rounded-full bg-surface">
          <div
            v-if="credits.status?.weekly.limit"
            class="h-full rounded-full transition-[width] duration-500"
            :class="progressClass(credits.weeklyPercent)"
            :style="{ width: `${credits.weeklyPercent}%` }"
          />
          <div v-else class="h-full w-full rounded-full bg-fg/65" />
        </div>
        <p class="mt-1.5 text-[11.5px] tabular-nums text-fg-faint">
          {{
            credits.status?.weekly.limit
              ? `${fmtReset(credits.status.weekly.reset_at)} 重置`
              : "无周限额限制"
          }}
        </p>
      </div>

      <div v-if="credits.tier !== 'pro'" class="rounded-2xl bg-canvas/75 p-3 dark:bg-canvas/80">
        <div class="flex items-center justify-between text-[12.5px]">
          <span class="font-medium text-fg-muted">5 小时剩余</span>
          <span class="font-semibold tabular-nums text-fg">
            {{ credits.status ? `${credits.fiveHourPercent}%` : "—" }}
          </span>
        </div>
        <div class="mt-2 h-1.5 overflow-clip rounded-full bg-surface">
          <div
            class="h-full rounded-full transition-[width] duration-500"
            :class="progressClass(credits.fiveHourPercent)"
            :style="{ width: `${credits.fiveHourPercent}%` }"
          />
        </div>
        <p class="mt-1.5 text-[11.5px] tabular-nums text-fg-faint">
          {{ credits.status ? `${fmtReset(credits.status.five_hour.reset_at)} 重置` : "加载中…" }}
        </p>
      </div>
    </div>

    <!-- 3-tier comparison -->
    <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
      <div
        v-for="p in displayPlans"
        :key="p.tier"
        class="flex flex-col rounded-2xl px-3.5 py-3 transition-colors"
        :class="
          p.tier === credits.tier
            ? 'bg-canvas ring-1 ring-accent/55 dark:bg-active/65'
            : 'bg-canvas/55 dark:bg-canvas/45'
        "
      >
        <div class="flex items-center justify-between gap-1.5">
          <span class="text-[13.5px] font-semibold text-fg">{{ p.label }}</span>
          <span
            v-if="p.tier === credits.tier"
            class="rounded-full bg-accent-weak px-2 py-0.5 text-[10.5px] font-medium leading-none text-accent"
          >
            当前
          </span>
        </div>
        <p class="mt-1 text-[12px] leading-snug text-fg-muted">{{ p.summary || planTagline(p.tier) }}</p>
        <dl class="mt-2.5 space-y-1 border-t border-line/60 pt-2 text-[11.5px]">
          <div class="flex items-center justify-between gap-2">
            <dt class="text-fg-faint">每周额度</dt>
            <dd class="font-medium tabular-nums text-fg">{{ p.weekly_credits }} 积分</dd>
          </div>
          <div class="flex items-center justify-between gap-2">
            <dt class="text-fg-faint">5 小时额度</dt>
            <dd class="font-medium tabular-nums text-fg">
              {{ p.five_hour_credits !== null ? `${p.five_hour_credits} 积分` : "不限" }}
            </dd>
          </div>
          <div class="flex items-center justify-between gap-2">
            <dt class="text-fg-faint">最大并发运行</dt>
            <dd class="font-medium tabular-nums text-fg">{{ p.max_runs_per_user }} 个</dd>
          </div>
          <div class="flex items-center justify-between gap-2">
            <dt class="text-fg-faint">单轮工具调用</dt>
            <dd class="font-medium tabular-nums text-fg">
              {{ p.max_tool_iterations ?? (p.tier === "pro" ? 200 : p.tier === "plus" ? 60 : 30) }} 次
            </dd>
          </div>
        </dl>
      </div>
    </div>

    <!-- Inline invite code redemption -->
    <form
      method="POST"
      action="/api/users/me/redeem"
      aria-labelledby="label-redeem-code"
      class="mt-auto pt-1"
      @submit.prevent="redeem"
    >
      <div class="mb-1.5 flex items-center justify-between gap-2">
        <label id="label-redeem-code" for="settings-redeem-code" class="text-[12.5px] font-medium text-fg-muted">
          兑换邀请码
        </label>
        <span v-if="redeemErr" id="redeem-error" role="alert" class="truncate text-[12px] text-danger">
          {{ redeemErr }}
        </span>
        <span v-else-if="redeemMsg" role="status" aria-live="polite" class="truncate text-[12px] text-success">
          {{ redeemMsg }}
        </span>
      </div>
      <div class="flex items-center gap-2">
        <input
          id="settings-redeem-code"
          ref="redeemInput"
          v-model="redeemCode"
          name="code"
          type="text"
          maxlength="32"
          placeholder="WZ-XXXX-XXXX-XXXX-XXXX"
          autocorrect="off"
          autocapitalize="none"
          spellcheck="false"
          enterkeyhint="done"
          :aria-invalid="redeemErr ? 'true' : undefined"
          :aria-describedby="redeemErr ? 'redeem-error' : undefined"
          class="focus-ring h-9.5 min-w-0 flex-1 rounded-xl border bg-canvas px-3 font-mono text-[13px] text-fg transition-colors placeholder:font-sans placeholder:text-fg-faint hover:border-line-strong"
          :class="redeemErr ? 'border-danger' : 'border-line/80'"
          @input="redeemErr = null; redeemMsg = null"
        />
        <BaseButton type="submit" size="sm" rounded="full" :loading="redeeming" class="shrink-0">兑换</BaseButton>
      </div>
    </form>
  </div>
</template>
