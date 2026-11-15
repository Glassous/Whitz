<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type { AuditLog, AuditLogList, Overview } from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import Icon from "../components/ui/Icon.vue";

const data = ref<Overview | null>(null);
const recent = ref<AuditLog[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const numberFormat = new Intl.NumberFormat("zh-CN");

const stats = computed(() => {
  const o = data.value;
  if (!o) return [];
  return [
    { label: "用户总数", value: o.users.total, hint: `活跃 ${o.users.active}` },
    { label: "今日消息", value: o.usage_today.messages, hint: `运行 ${o.usage_today.runs} 次` },
    { label: "今日 Token", value: o.usage_today.tokens, hint: `上限 ${numberFormat.format(o.limits.daily_token_limit)}` },
    { label: "活跃任务", value: o.conversations.active_runs, hint: `会话 ${o.conversations.total}` },
    { label: "今日新增用户", value: o.users.new_today, hint: `管理员 ${o.users.admins}` },
    { label: "近 24h 失败操作", value: o.audit_24h.failures, hint: "审计日志" },
    { label: "近 24h 严重事件", value: o.audit_24h.critical, hint: "审计日志" },
  ];
});

function fmt(value: number): string {
  return numberFormat.format(value);
}

function fmtTime(value: string): string {
  return new Date(value).toLocaleString();
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [overview, audits] = await Promise.all([
      api.get<Overview>("/admin/overview"),
      api.get<AuditLogList>("/admin/audit-logs?page=1&page_size=8"),
    ]);
    data.value = overview;
    recent.value = audits.items;
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    loading.value = false;
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

    <template v-else-if="data">
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div v-for="s in stats" :key="s.label" class="rounded-2xl border border-line bg-canvas p-4">
          <p class="text-[12px] text-fg-muted">{{ s.label }}</p>
          <p class="mt-2 text-[26px] font-semibold leading-none tabular-nums tracking-tight text-fg">
            {{ fmt(s.value) }}
          </p>
          <p class="mt-2 text-[11px] text-fg-faint">{{ s.hint }}</p>
        </div>
      </div>

      <div class="mt-6 grid gap-4 lg:grid-cols-3">
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
          <h2 class="text-[13.5px] font-medium text-fg">资源限制</h2>
          <dl class="mt-3 space-y-2.5">
            <div class="flex items-center justify-between gap-3">
              <dt class="text-[12px] text-fg-muted">每日消息</dt>
              <dd class="text-[12px] tabular-nums text-fg">{{ fmt(data.limits.daily_message_limit) }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-[12px] text-fg-muted">每日 Token</dt>
              <dd class="text-[12px] tabular-nums text-fg">{{ fmt(data.limits.daily_token_limit) }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-[12px] text-fg-muted">全局并发任务</dt>
              <dd class="text-[12px] tabular-nums text-fg">{{ data.limits.max_concurrent_runs }}</dd>
            </div>
            <div class="flex items-center justify-between gap-3">
              <dt class="text-[12px] text-fg-muted">单用户并发任务</dt>
              <dd class="text-[12px] tabular-nums text-fg">{{ data.limits.max_concurrent_runs_per_user }}</dd>
            </div>
          </dl>
          <p class="mt-4 border-t border-line pt-3 text-[11px] leading-relaxed text-fg-faint">
            限制由服务端环境变量控制，修改后重启 API 生效。
          </p>
        </section>
      </div>
    </template>
  </div>
</template>
