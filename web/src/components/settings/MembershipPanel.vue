<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useAuthStore } from "../../stores/auth";
import { useCreditsStore } from "../../stores/credits";
import BaseInput from "../ui/BaseInput.vue";
import BaseButton from "../ui/BaseButton.vue";
import type { MembershipTier } from "../../types";

const auth = useAuthStore();
const credits = useCreditsStore();

const redeemCode = ref("");
const redeemMsg = ref<string | null>(null);
const redeemErr = ref<string | null>(null);
const redeeming = ref(false);

const tierTone = computed(() => {
  if (credits.tier === "pro") return "border-[#7C6BF0]/40 bg-[#7C6BF0]/10 text-[#6B5CE0]";
  if (credits.tier === "plus") return "border-accent/40 bg-accent-weak text-accent";
  return "border-line bg-surface text-fg-muted";
});

function fmtDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "长期有效";
}

function fmtDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
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
  if (tier === "pro") return "无 5 小时限制，可一次用完整周额度";
  if (tier === "plus") return "更高的周额度，5 小时分段可用";
  return "基础周额度，5 小时分段可用";
}

async function redeem() {
  redeemMsg.value = null;
  redeemErr.value = null;
  if (!redeemCode.value.trim()) {
    redeemErr.value = "请输入邀请码";
    return;
  }
  redeeming.value = true;
  try {
    const info = await credits.redeem(redeemCode.value);
    redeemCode.value = "";
    redeemMsg.value = `兑换成功，当前为 ${info.tier_label}，有效期至 ${fmtDate(info.expires_at)}`;
    await auth.refreshUser();
  } catch (e: any) {
    redeemErr.value = e?.detail?.detail ?? "兑换失败，请检查邀请码";
  } finally {
    redeeming.value = false;
  }
}

onMounted(() => {
  void credits.fetch();
});
</script>

<template>
  <div class="space-y-4">
    <div class="rounded-2xl border p-4" :class="tierTone">
      <div class="flex items-start justify-between gap-4">
        <div>
          <p class="text-[11px] uppercase tracking-wide opacity-70">会员档位</p>
          <p class="mt-1 text-[22px] font-semibold leading-none">{{ credits.tierLabel }}</p>
          <p class="mt-1.5 text-[12px]">
            {{
              credits.tier === "free"
                ? "免费额度按周与 5 小时滚动刷新"
                : `有效期至 ${fmtDate(credits.status?.expires_at ?? null)}`
            }}
          </p>
        </div>
        <div class="text-right">
          <p class="text-[11px] uppercase tracking-wide opacity-70">还剩</p>
          <p class="mt-1 text-[22px] font-semibold leading-none tabular-nums">
            {{ availablePercent === null ? "—" : `${availablePercent}%` }}
          </p>
          <p class="mt-1.5 text-[11px] opacity-80">额度按滚动窗口恢复</p>
        </div>
      </div>
      <p v-if="credits.overdrawn" class="mt-3 rounded-lg bg-danger-weak px-2.5 py-1.5 text-[12px] text-danger">
        额度已用完，将在 {{ fmtDateTime(credits.nextResetAt) }} 刷新后恢复。
      </p>
    </div>

    <p v-if="credits.error" class="rounded-xl bg-danger-weak px-3 py-2 text-[12px] text-danger">
      {{ credits.error }}
    </p>

    <div class="space-y-4 rounded-2xl border border-line bg-canvas p-4">
      <div>
        <div class="flex items-center justify-between text-[12px]">
          <span class="text-fg-muted">本周剩余</span>
          <span class="tabular-nums text-fg">
            {{ credits.status?.weekly.limit ? `${credits.weeklyPercent}%` : "不限" }}
          </span>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
          <div
            v-if="credits.status?.weekly.limit"
            class="h-full rounded-full transition-[width] duration-500"
            :class="progressClass(credits.weeklyPercent)"
            :style="{ width: `${credits.weeklyPercent}%` }"
          />
          <div v-else class="h-full w-full rounded-full bg-gradient-to-r from-accent/60 to-[#7C6BF0]/60" />
        </div>
        <p class="mt-1.5 text-[11px] text-fg-faint">
          {{
            credits.status?.weekly.limit
              ? `下次刷新 ${fmtDateTime(credits.status?.weekly.reset_at ?? null)}`
              : "当前档位无周限额"
          }}
        </p>
      </div>
      <div v-if="credits.status && credits.tier !== 'pro'">
        <div class="flex items-center justify-between text-[12px]">
          <span class="text-fg-muted">5 小时剩余</span>
          <span class="tabular-nums text-fg">{{ credits.fiveHourPercent }}%</span>
        </div>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-surface">
          <div
            class="h-full rounded-full transition-[width] duration-500"
            :class="progressClass(credits.fiveHourPercent)"
            :style="{ width: `${credits.fiveHourPercent}%` }"
          />
        </div>
        <p class="mt-1.5 text-[11px] text-fg-faint">
          下次刷新 {{ fmtDateTime(credits.status?.five_hour.reset_at ?? null) }}
        </p>
      </div>
    </div>

    <div class="grid gap-2 sm:grid-cols-3">
      <div
        v-for="p in credits.status?.plans ?? []"
        :key="p.tier"
        class="rounded-xl border p-3"
        :class="p.tier === credits.tier ? 'border-accent bg-accent-weak/40' : 'border-line'"
      >
        <div class="flex items-center justify-between">
          <p class="text-[13px] font-semibold text-fg">{{ p.label }}</p>
          <span v-if="p.tier === credits.tier" class="text-[10px] font-medium text-accent">当前</span>
        </div>
        <p class="mt-2 text-[12px] font-medium leading-relaxed text-fg-muted">
          {{ planTagline(p.tier) }}
        </p>
      </div>
    </div>

    <div class="rounded-2xl border border-line bg-canvas p-4">
      <h3 class="text-[13px] font-semibold text-fg">兑换邀请码</h3>
      <p class="mt-0.5 text-[12px] text-fg-muted">输入管理员提供的兑换码，升级或续期会员。</p>
      <div class="mt-3 flex flex-col gap-2 sm:flex-row">
        <div class="flex-1">
          <BaseInput v-model="redeemCode" placeholder="WZ-XXXX-XXXX-XXXX-XXXX" />
        </div>
        <BaseButton :loading="redeeming" @click="redeem">兑换</BaseButton>
      </div>
      <p v-if="redeemErr" class="mt-2 text-[12px] text-danger">{{ redeemErr }}</p>
      <p v-if="redeemMsg" class="mt-2 text-[12px] text-success">{{ redeemMsg }}</p>
    </div>
  </div>
</template>
