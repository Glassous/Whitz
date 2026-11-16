import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import type { CreditStatus } from "../types";

function percentOf(used: number, limit: number | null): number {
  if (!limit) return 0;
  return Math.max(0, Math.min(100, Math.round(((limit - used) / limit) * 100)));
}

export const useCreditsStore = defineStore("credits", () => {
  const status = ref<CreditStatus | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const tier = computed(() => status.value?.tier ?? "free");
  const tierLabel = computed(() => status.value?.tier_label ?? "Free");
  const remaining = computed(() => status.value?.remaining ?? 0);
  const overdrawn = computed(() => status.value?.overdrawn ?? false);
  const weeklyPercent = computed(() =>
    status.value ? percentOf(status.value.weekly.used, status.value.weekly.limit) : 0,
  );
  const fiveHourPercent = computed(() =>
    status.value ? percentOf(status.value.five_hour.used, status.value.five_hour.limit) : 0,
  );
  const nextResetAt = computed(() => {
    const current = status.value;
    if (!current) return null;
    const resets = [current.weekly.reset_at];
    if (current.tier !== "pro") resets.push(current.five_hour.reset_at);
    return resets.reduce((a, b) => (new Date(a).getTime() <= new Date(b).getTime() ? a : b));
  });

  async function fetch() {
    loading.value = true;
    error.value = null;
    try {
      status.value = await api.get<CreditStatus>("/users/me/credits");
    } catch (e: any) {
      error.value = e?.detail?.detail ?? e?.message ?? "积分信息加载失败";
    } finally {
      loading.value = false;
    }
  }

  async function redeem(code: string): Promise<CreditStatus> {
    const next = await api.post<CreditStatus>("/users/me/redeem", { code: code.trim() });
    status.value = next;
    return next;
  }

  function reset() {
    status.value = null;
    loading.value = false;
    error.value = null;
  }

  return {
    status,
    loading,
    error,
    tier,
    tierLabel,
    remaining,
    overdrawn,
    weeklyPercent,
    fiveHourPercent,
    nextResetAt,
    fetch,
    redeem,
    reset,
  };
});
