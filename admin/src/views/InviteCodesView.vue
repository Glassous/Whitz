<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type { InviteCode, InviteCodeList, InviteRedemption } from "../types";
import InviteCodeForm from "../components/InviteCodeForm.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

const data = ref<InviteCodeList | null>(null);
const filterTier = ref("");
const filterStatus = ref("");
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const error = ref<string | null>(null);

const copiedId = ref<string | null>(null);
const disableTarget = ref<InviteCode | null>(null);
const disableLoading = ref(false);
const enablingId = ref<string | null>(null);

const redemptionsTarget = ref<InviteCode | null>(null);
const redemptions = ref<InviteRedemption[]>([]);
const redemptionsLoading = ref(false);
const redemptionsError = ref<string | null>(null);
let redemptionsSeq = 0;

let copyTimer: number | null = null;

const totalPages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.total / pageSize)) : 1));

function fmtTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "永久有效";
}

function statusOf(row: InviteCode): { label: string; tone: "green" | "gray" | "red" | "amber" } {
  if (!row.is_active) return { label: "已停用", tone: "red" };
  if (row.expires_at && new Date(row.expires_at).getTime() <= Date.now()) return { label: "已过期", tone: "amber" };
  if (row.used_count >= row.max_uses) return { label: "已用完", tone: "gray" };
  return { label: "可用", tone: "green" };
}

function usageWidth(row: InviteCode): string {
  const ratio = Math.min(1, row.used_count / Math.max(1, row.max_uses));
  return `${Math.round(ratio * 100)}%`;
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) });
    if (filterTier.value) params.set("tier", filterTier.value);
    if (filterStatus.value) params.set("is_active", filterStatus.value);
    data.value = await api.get<InviteCodeList>(`/admin/invite-codes?${params.toString()}`);
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    loading.value = false;
  }
}

function filter() {
  page.value = 1;
  void load();
}

function go(next: number) {
  page.value = next;
  void load();
}

async function copy(text: string, id: string) {
  try {
    await navigator.clipboard.writeText(text);
    copiedId.value = id;
    if (copyTimer) window.clearTimeout(copyTimer);
    copyTimer = window.setTimeout(() => {
      copiedId.value = null;
    }, 1200);
  } catch {
    copiedId.value = null;
  }
}

async function confirmDisable() {
  const target = disableTarget.value;
  if (!target) return;
  disableLoading.value = true;
  try {
    await api.patch(`/admin/invite-codes/${target.id}`, { is_active: false });
    disableTarget.value = null;
    await load();
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    disableLoading.value = false;
  }
}

async function enableCode(row: InviteCode) {
  enablingId.value = row.id;
  error.value = null;
  try {
    await api.patch(`/admin/invite-codes/${row.id}`, { is_active: true });
    await load();
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    enablingId.value = null;
  }
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

async function openRedemptions(row: InviteCode) {
  const seq = ++redemptionsSeq;
  redemptionsTarget.value = row;
  redemptions.value = [];
  redemptionsError.value = null;
  redemptionsLoading.value = true;
  try {
    const res = await api.get<InviteRedemption[]>(`/admin/invite-codes/${row.id}/redemptions`);
    if (seq !== redemptionsSeq) return;
    redemptions.value = res;
  } catch (e: unknown) {
    if (seq !== redemptionsSeq) return;
    redemptionsError.value = readableError(e);
  } finally {
    if (seq === redemptionsSeq) redemptionsLoading.value = false;
  }
}

function closeRedemptions() {
  redemptionsSeq += 1;
  redemptionsTarget.value = null;
  redemptions.value = [];
  redemptionsError.value = null;
}

onMounted(load);
onBeforeUnmount(() => {
  if (copyTimer) window.clearTimeout(copyTimer);
});
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-[20px] font-semibold tracking-tight text-fg">邀请码</h1>
      <p class="mt-1 text-[12px] text-fg-faint">生成会员兑换码，用户在设置页兑换后即可升级 Plus / Pro</p>
    </div>

    <p v-if="error" class="mb-4 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

    <div class="grid gap-4 lg:grid-cols-[320px_1fr]">
      <InviteCodeForm @created="load" />

      <section class="min-w-0 overflow-hidden rounded-2xl border border-line bg-canvas">
        <div class="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <h2 class="text-[13.5px] font-medium text-fg">已生成的邀请码</h2>
          <div class="ml-auto flex items-center gap-2">
            <select
              v-model="filterTier"
              class="focus-ring h-8 rounded-lg border border-line bg-canvas px-2 text-[12px] text-fg"
              @change="filter"
            >
              <option value="">全部档位</option>
              <option value="plus">Plus</option>
              <option value="pro">Pro</option>
            </select>
            <select
              v-model="filterStatus"
              class="focus-ring h-8 rounded-lg border border-line bg-canvas px-2 text-[12px] text-fg"
              @change="filter"
            >
              <option value="">全部状态</option>
              <option value="true">启用</option>
              <option value="false">停用</option>
            </select>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full min-w-[720px] text-sm">
            <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
              <tr>
                <th class="px-4 py-2.5 font-medium">兑换码</th>
                <th class="px-4 py-2.5 font-medium">档位</th>
                <th class="px-4 py-2.5 font-medium">使用情况</th>
                <th class="px-4 py-2.5 font-medium">有效期</th>
                <th class="px-4 py-2.5 font-medium">状态</th>
                <th class="px-4 py-2.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-if="loading">
                <td colspan="6" class="px-4 py-12 text-center text-[13px] text-fg-faint">加载中…</td>
              </tr>
              <tr v-else-if="!data?.items.length">
                <td colspan="6" class="px-4 py-12 text-center text-[13px] text-fg-faint">还没有邀请码</td>
              </tr>
              <tr v-for="row in data?.items ?? []" :key="row.id" class="transition-colors hover:bg-surface">
                <td class="px-4 py-3">
                  <button
                    class="focus-ring inline-flex items-center gap-1.5 rounded-md font-mono text-[12px] text-fg transition-opacity hover:opacity-70"
                    @click="copy(row.code, row.id)"
                  >
                    {{ row.code }}
                    <span class="text-[10.5px] text-accent">{{ copiedId === row.id ? "已复制" : "复制" }}</span>
                  </button>
                  <p v-if="row.note" class="mt-0.5 max-w-[220px] truncate text-[11px] text-fg-faint">{{ row.note }}</p>
                </td>
                <td class="px-4 py-3">
                  <BaseBadge :tone="row.tier === 'pro' ? 'brand' : 'blue'">{{ row.tier === "pro" ? "Pro" : "Plus" }}</BaseBadge>
                  <p class="mt-0.5 text-[11px] text-fg-faint">{{ row.duration_days }} 天</p>
                </td>
                <td class="px-4 py-3">
                  <p class="text-[12px] tabular-nums text-fg">{{ row.used_count }} / {{ row.max_uses }}</p>
                  <div class="mt-1 h-1 w-24 overflow-hidden rounded-full bg-surface">
                    <div class="h-full rounded-full bg-accent transition-[width] duration-300" :style="{ width: usageWidth(row) }" />
                  </div>
                </td>
                <td class="whitespace-nowrap px-4 py-3 text-[12px] text-fg-faint">
                  <p>码 {{ fmtTime(row.expires_at) }}</p>
                  <p class="text-[11px]">生成 {{ new Date(row.created_at).toLocaleDateString() }}</p>
                </td>
                <td class="px-4 py-3">
                  <BaseBadge :tone="statusOf(row).tone">{{ statusOf(row).label }}</BaseBadge>
                </td>
                <td class="px-4 py-3 text-right">
                  <div class="flex items-center justify-end gap-1.5 whitespace-nowrap">
                    <BaseButton size="sm" variant="ghost" @click="openRedemptions(row)">兑换明细</BaseButton>
                    <BaseButton
                      v-if="row.is_active"
                      size="sm"
                      variant="secondary"
                      @click="disableTarget = row"
                    >
                      停用
                    </BaseButton>
                    <BaseButton
                      v-else
                      size="sm"
                      variant="primary"
                      :loading="enablingId === row.id"
                      @click="enableCode(row)"
                    >
                      重新启用
                    </BaseButton>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="flex items-center justify-center gap-3 border-t border-line px-4 py-3">
          <BaseButton size="sm" variant="secondary" :disabled="page <= 1 || loading" @click="go(page - 1)">
            <Icon name="chevron-left" :size="14" />
            上一页
          </BaseButton>
          <span class="text-[12px] tabular-nums text-fg-muted">{{ page }} / {{ totalPages }}</span>
          <BaseButton size="sm" variant="secondary" :disabled="page >= totalPages || loading" @click="go(page + 1)">
            下一页
            <Icon name="chevron-right" :size="14" />
          </BaseButton>
        </div>
      </section>
    </div>

    <BaseModal :open="!!disableTarget" title="停用邀请码" width="26rem" @close="disableTarget = null">
      <p class="text-[13px] leading-relaxed text-fg-muted">
        停用后
        <span class="font-mono text-[12px] text-fg">{{ disableTarget?.code }}</span>
        将无法再被兑换，已兑换的会员权益不受影响。
      </p>
      <template #footer>
        <BaseButton variant="secondary" @click="disableTarget = null">取消</BaseButton>
        <BaseButton variant="danger" :loading="disableLoading" @click="confirmDisable">确认停用</BaseButton>
      </template>
    </BaseModal>

    <BaseModal
      :open="!!redemptionsTarget"
      :title="redemptionsTarget ? `兑换明细 · ${redemptionsTarget.code}` : '兑换明细'"
      width="40rem"
      @close="closeRedemptions"
    >
      <div v-if="redemptionsTarget" class="space-y-3">
        <div class="flex flex-wrap items-center gap-2 rounded-xl bg-surface px-3 py-2 text-[12px] text-fg-muted">
          <BaseBadge :tone="tierTone(redemptionsTarget.tier)">{{ tierLabel(redemptionsTarget.tier) }}</BaseBadge>
          <span>时长 {{ redemptionsTarget.duration_days }} 天</span>
          <span class="ml-auto tabular-nums">
            已使用 {{ redemptionsTarget.used_count }} / {{ redemptionsTarget.max_uses }}
          </span>
        </div>

        <p v-if="redemptionsError" class="rounded-xl bg-danger-weak px-3 py-2 text-[12.5px] text-danger">
          {{ redemptionsError }}
        </p>

        <div class="overflow-x-auto rounded-xl border border-line">
          <table class="w-full min-w-[440px] text-left text-[12.5px]">
            <thead class="bg-surface text-[11px] uppercase tracking-wide text-fg-faint">
              <tr>
                <th class="px-3 py-2.5 font-medium">用户邮箱</th>
                <th class="px-3 py-2.5 font-medium">档位</th>
                <th class="px-3 py-2.5 font-medium">时长</th>
                <th class="px-3 py-2.5 font-medium">兑换时间</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-if="redemptionsLoading">
                <td colspan="4" class="px-3 py-10 text-center text-fg-faint">加载兑换记录中…</td>
              </tr>
              <tr v-else-if="!redemptions.length">
                <td colspan="4" class="px-3 py-10 text-center text-fg-faint">该邀请码暂无兑换记录</td>
              </tr>
              <tr v-for="r in redemptions" :key="r.id" class="hover:bg-surface/60">
                <td class="px-3 py-2.5 text-fg">{{ r.user_email ?? r.user_id }}</td>
                <td class="px-3 py-2.5">
                  <BaseBadge :tone="tierTone(r.tier)">{{ tierLabel(r.tier) }}</BaseBadge>
                </td>
                <td class="px-3 py-2.5 tabular-nums text-fg-muted">{{ r.duration_days }} 天</td>
                <td class="whitespace-nowrap px-3 py-2.5 tabular-nums text-fg-faint">
                  {{ new Date(r.redeemed_at).toLocaleString() }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <template #footer>
        <BaseButton variant="secondary" @click="closeRedemptions">关闭</BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
