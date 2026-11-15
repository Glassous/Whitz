<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type { AuditLog, AuditLogList } from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

const data = ref<AuditLogList | null>(null);
const query = ref("");
const severity = ref("");
const outcome = ref("");
const page = ref(1);
const pageSize = 50;
const loading = ref(false);
const error = ref<string | null>(null);
const selected = ref<AuditLog | null>(null);

const totalPages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.total / pageSize)) : 1));

const severityTone = (row: AuditLog) =>
  row.severity === "critical" ? "red" : row.severity === "warning" ? "amber" : "gray";

const severityLabel = (row: AuditLog) =>
  row.severity === "critical" ? "严重" : row.severity === "warning" ? "警告" : "信息";

function fmtTime(value: string): string {
  return new Date(value).toLocaleString();
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) });
    if (query.value.trim()) params.set("q", query.value.trim());
    if (severity.value) params.set("severity", severity.value);
    if (outcome.value) params.set("outcome", outcome.value);
    data.value = await api.get<AuditLogList>(`/admin/audit-logs?${params.toString()}`);
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    loading.value = false;
  }
}

function search() {
  page.value = 1;
  void load();
}

function go(next: number) {
  page.value = next;
  void load();
}

onMounted(load);
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-[20px] font-semibold tracking-tight text-fg">审计日志</h1>
      <p class="mt-1 text-[12px] text-fg-faint">登录、会话、管理与安全相关操作记录</p>
    </div>

    <div class="mb-4 flex flex-wrap items-center gap-2">
      <div class="w-full sm:w-72">
        <BaseInput v-model="query" placeholder="搜索邮箱、动作或对象 ID…" @keydown.enter="search" />
      </div>
      <select
        v-model="severity"
        class="focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部级别</option>
        <option value="info">信息</option>
        <option value="warning">警告</option>
        <option value="critical">严重</option>
      </select>
      <select
        v-model="outcome"
        class="focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部结果</option>
        <option value="success">成功</option>
        <option value="failure">失败</option>
      </select>
      <BaseButton variant="secondary" @click="search">搜索</BaseButton>
      <BaseButton variant="ghost" :loading="loading" @click="load">
        <Icon name="refresh" :size="14" />
        刷新
      </BaseButton>
      <span v-if="data" class="ml-auto text-[13px] tabular-nums text-fg-faint">共 {{ data.total }} 条</span>
    </div>

    <p v-if="error" class="mb-3 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

    <div class="overflow-x-auto rounded-2xl border border-line bg-canvas">
      <table class="w-full min-w-[820px] text-sm">
        <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
          <tr>
            <th class="px-4 py-3 font-medium">时间</th>
            <th class="px-4 py-3 font-medium">操作者</th>
            <th class="px-4 py-3 font-medium">动作</th>
            <th class="px-4 py-3 font-medium">结果</th>
            <th class="px-4 py-3 font-medium">级别</th>
            <th class="px-4 py-3 font-medium">IP</th>
            <th class="px-4 py-3 text-right font-medium">详情</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-if="loading">
            <td colspan="7" class="px-4 py-12 text-center text-[13px] text-fg-faint">加载中…</td>
          </tr>
          <tr v-else-if="!data?.items.length">
            <td colspan="7" class="px-4 py-12 text-center text-[13px] text-fg-faint">暂无审计记录</td>
          </tr>
          <tr v-for="row in data?.items ?? []" :key="row.id" class="transition-colors hover:bg-surface">
            <td class="whitespace-nowrap px-4 py-3 text-[12px] tabular-nums text-fg-faint">
              {{ fmtTime(row.created_at) }}
            </td>
            <td class="max-w-[180px] truncate px-4 py-3 text-[12px] text-fg-muted">
              {{ row.actor_email ?? "—" }}
            </td>
            <td class="px-4 py-3">
              <p class="font-mono text-[12px] text-fg">{{ row.action }}</p>
              <p v-if="row.target_type" class="mt-0.5 text-[10.5px] text-fg-faint">
                {{ row.target_type }} · {{ row.target_id ?? "—" }}
              </p>
            </td>
            <td class="px-4 py-3">
              <BaseBadge :tone="row.outcome === 'success' ? 'green' : 'red'">
                {{ row.outcome === "success" ? "成功" : "失败" }}
              </BaseBadge>
            </td>
            <td class="px-4 py-3">
              <BaseBadge :tone="severityTone(row)">{{ severityLabel(row) }}</BaseBadge>
            </td>
            <td class="whitespace-nowrap px-4 py-3 text-[12px] tabular-nums text-fg-faint">
              {{ row.ip ?? "—" }}
            </td>
            <td class="px-4 py-3 text-right">
              <BaseButton size="sm" variant="ghost" @click="selected = row">查看</BaseButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-4 flex items-center justify-center gap-3">
      <BaseButton size="sm" variant="secondary" :disabled="page <= 1 || loading" @click="go(page - 1)">
        <Icon name="chevron-left" :size="14" />
        上一页
      </BaseButton>
      <span class="text-[13px] tabular-nums text-fg-muted">{{ page }} / {{ totalPages }}</span>
      <BaseButton size="sm" variant="secondary" :disabled="page >= totalPages || loading" @click="go(page + 1)">
        下一页
        <Icon name="chevron-right" :size="14" />
      </BaseButton>
    </div>

    <BaseModal :open="!!selected" title="审计详情" width="40rem" @close="selected = null">
      <div v-if="selected" class="space-y-3">
        <dl class="grid grid-cols-[92px_1fr] gap-x-3 gap-y-2 text-[12.5px]">
          <dt class="text-fg-faint">时间</dt>
          <dd class="tabular-nums text-fg">{{ fmtTime(selected.created_at) }}</dd>
          <dt class="text-fg-faint">操作者</dt>
          <dd class="text-fg">{{ selected.actor_email ?? "—" }}</dd>
          <dt class="text-fg-faint">动作</dt>
          <dd class="font-mono text-fg">{{ selected.action }}</dd>
          <dt class="text-fg-faint">对象</dt>
          <dd class="break-all text-fg">
            {{ selected.target_type ? `${selected.target_type} · ${selected.target_id ?? "—"}` : "—" }}
          </dd>
          <dt class="text-fg-faint">结果 / 级别</dt>
          <dd class="flex items-center gap-2">
            <BaseBadge :tone="selected.outcome === 'success' ? 'green' : 'red'">
              {{ selected.outcome === "success" ? "成功" : "失败" }}
            </BaseBadge>
            <BaseBadge :tone="severityTone(selected)">{{ severityLabel(selected) }}</BaseBadge>
          </dd>
          <dt class="text-fg-faint">IP</dt>
          <dd class="tabular-nums text-fg">{{ selected.ip ?? "—" }}</dd>
          <dt class="text-fg-faint">请求 ID</dt>
          <dd class="break-all font-mono text-[11.5px] text-fg">{{ selected.request_id ?? "—" }}</dd>
          <dt class="text-fg-faint">会话 ID</dt>
          <dd class="break-all font-mono text-[11.5px] text-fg">{{ selected.session_id ?? "—" }}</dd>
          <dt class="text-fg-faint">User-Agent</dt>
          <dd class="break-all text-[11.5px] text-fg-muted">{{ selected.user_agent ?? "—" }}</dd>
        </dl>

        <div v-if="selected.metadata">
          <p class="mb-1.5 text-[12px] text-fg-faint">附加信息</p>
          <pre class="mono-block rounded-xl border border-line bg-surface px-3 py-2.5 text-fg">{{
            JSON.stringify(selected.metadata, null, 2)
          }}</pre>
        </div>
      </div>
    </BaseModal>
  </div>
</template>
