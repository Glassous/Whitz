<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import type {
  AuditAnalytics,
  AuditLog,
  AuditLogList,
  AuditTraceResponse,
  AuditVerifyResult,
} from "../types";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

const data = ref<AuditLogList | null>(null);
const analytics = ref<AuditAnalytics | null>(null);
const verifyResult = ref<AuditVerifyResult | null>(null);

const query = ref("");
const actionPrefix = ref("");
const ipFilter = ref("");
const minRisk = ref("");
const severity = ref("");
const outcome = ref("");
const maskPii = ref(true);

const page = ref(1);
const pageSize = 50;
const loading = ref(false);
const verifying = ref(false);
const exporting = ref(false);
const error = ref<string | null>(null);

const selected = ref<AuditLog | null>(null);
const traceOpen = ref(false);
const traceLoading = ref(false);
const traceData = ref<AuditTraceResponse | null>(null);

const totalPages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.total / pageSize)) : 1));

const severityTone = (row: AuditLog) =>
  row.severity === "critical" ? "red" : row.severity === "warning" ? "amber" : "gray";

const severityLabel = (row: AuditLog) =>
  row.severity === "critical" ? "严重" : row.severity === "warning" ? "警告" : "信息";

const riskTone = (score: number): "red" | "amber" | "gray" =>
  score >= 70 ? "red" : score >= 45 ? "amber" : "gray";

function fmtTime(value: string): string {
  return new Date(value).toLocaleString("zh-CN");
}

function buildFilterParams(includePagination = true): URLSearchParams {
  const params = new URLSearchParams();
  if (includePagination) {
    params.set("page", String(page.value));
    params.set("page_size", String(pageSize));
  }
  if (query.value.trim()) params.set("q", query.value.trim());
  if (actionPrefix.value) params.set("action_prefix", actionPrefix.value);
  if (ipFilter.value.trim()) params.set("ip", ipFilter.value.trim());
  if (minRisk.value) params.set("min_risk", minRisk.value);
  if (severity.value) params.set("severity", severity.value);
  if (outcome.value) params.set("outcome", outcome.value);
  return params;
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [logsRes, anaRes] = await Promise.all([
      api.get<AuditLogList>(`/admin/audit-logs?${buildFilterParams(true).toString()}`),
      api.get<AuditAnalytics>("/admin/audit-logs/analytics?days=14"),
    ]);
    data.value = logsRes;
    analytics.value = anaRes;
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    loading.value = false;
  }
}

async function verifyChain() {
  verifying.value = true;
  error.value = null;
  try {
    verifyResult.value = await api.get<AuditVerifyResult>("/admin/audit-logs/verify?limit=2000");
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    verifying.value = false;
  }
}

async function exportLogs(fmt: "csv" | "jsonl") {
  exporting.value = true;
  error.value = null;
  try {
    const params = buildFilterParams(false);
    params.set("format", fmt);
    params.set("mask_pii", maskPii.value ? "true" : "false");
    await api.download(
      `/admin/audit-logs/export?${params.toString()}`,
      `whitz-audit.${fmt}`,
    );
    void load();
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    exporting.value = false;
  }
}

async function openTrace(traceId: string) {
  traceOpen.value = true;
  traceLoading.value = true;
  traceData.value = null;
  try {
    traceData.value = await api.get<AuditTraceResponse>(
      `/admin/audit-logs/trace/${encodeURIComponent(traceId)}`,
    );
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    traceLoading.value = false;
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

onMounted(() => {
  void load();
  void verifyChain();
});
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-[20px] font-semibold tracking-tight text-fg">纵深审计中心</h1>
        <p class="mt-1 text-[12px] text-fg-faint">
          HMAC-SHA256 防篡改哈希链、风险评分、Before/After Diff 与全链路 Trace 溯源
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <label class="inline-flex cursor-pointer items-center gap-1.5 rounded-xl border border-line bg-surface px-3 py-1.5 text-[12px] text-fg-muted">
          <input v-model="maskPii" type="checkbox" class="accent-accent" />
          导出脱敏 PII
        </label>
        <BaseButton size="sm" variant="secondary" :loading="exporting" @click="exportLogs('csv')">
          导出 CSV
        </BaseButton>
        <BaseButton size="sm" variant="secondary" :loading="exporting" @click="exportLogs('jsonl')">
          导出 JSONL
        </BaseButton>
        <BaseButton size="sm" variant="secondary" :loading="verifying" @click="verifyChain">
          <Icon name="shield" :size="14" />
          校验哈希链
        </BaseButton>
      </div>
    </div>

    <!-- Tamper-Evident Hash Chain Status Banner -->
    <div
      v-if="verifyResult"
      class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-[13px]"
      :class="
        verifyResult.valid
          ? 'border-success/30 bg-success-weak/50 text-fg'
          : 'border-danger/40 bg-danger-weak text-danger'
      "
    >
      <div class="flex items-center gap-2.5">
        <BaseBadge :tone="verifyResult.valid ? 'green' : 'red'">
          {{ verifyResult.valid ? "哈希链完整未篡改" : "检测到异常断链" }}
        </BaseBadge>
        <span>
          已校验 {{ verifyResult.checked_count }} 条记录（链式指纹 {{ verifyResult.hashed_count }} 条
          <template v-if="verifyResult.legacy_unhashed_count > 0">
            · 历史未加链 {{ verifyResult.legacy_unhashed_count }} 条
          </template>
          ）
        </span>
      </div>
      <span v-if="!verifyResult.valid && verifyResult.broken_at_id" class="font-mono text-[12px]">
        断链 ID #{{ verifyResult.broken_at_id }} ({{ verifyResult.reason }})
      </span>
    </div>

    <!-- 14d Audit Analytics Summary -->
    <div v-if="analytics" class="grid gap-3 lg:grid-cols-4">
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">近 14 天审计事件</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ analytics.summary.total_events }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">
          失败 {{ analytics.summary.failures }} ({{ analytics.summary.failure_rate_pct }}%)
        </p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">高风险操作 (Risk ≥ 60)</p>
        <p class="mt-1 text-xl font-semibold text-fg">{{ analytics.summary.high_risk_events }}</p>
        <p class="mt-0.5 text-[11px] text-fg-faint">管理变更 / 强停 / 越权</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">Top 高频动作</p>
        <div v-if="analytics.top_actions.length" class="mt-1.5 space-y-1 text-[12px]">
          <div v-for="a in analytics.top_actions.slice(0, 3)" :key="a.action" class="flex justify-between gap-2">
            <span class="truncate font-mono text-fg">{{ a.action }}</span>
            <span class="shrink-0 text-fg-muted">{{ a.count }}</span>
          </div>
        </div>
        <p v-else class="mt-2 text-[12px] text-fg-faint">暂无数据</p>
      </div>
      <div class="rounded-2xl border border-line bg-surface p-4">
        <p class="text-[12px] text-fg-muted">Top 失败来源 IP</p>
        <div v-if="analytics.top_ips.length" class="mt-1.5 space-y-1 text-[12px]">
          <div v-for="item in analytics.top_ips.slice(0, 3)" :key="item.ip" class="flex justify-between gap-2">
            <span class="truncate font-mono text-fg">{{ item.ip }}</span>
            <span class="shrink-0" :class="item.failures > 0 ? 'text-danger' : 'text-fg-muted'">
              {{ item.failures }} 败 / {{ item.count }}
            </span>
          </div>
        </div>
        <p v-else class="mt-2 text-[12px] text-fg-faint">暂无来源 IP</p>
      </div>
    </div>

    <!-- Filters -->
    <div class="flex flex-wrap items-center gap-2">
      <div class="w-full sm:w-64">
        <BaseInput v-model="query" placeholder="搜索邮箱、动作、对象或 Request ID…" @keydown.enter="search" />
      </div>
      <select
        v-model="actionPrefix"
        class="modern-select focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部模块</option>
        <option value="admin.">admin.*</option>
        <option value="auth.">auth.*</option>
        <option value="chat.">chat.*</option>
        <option value="ops.">ops.*</option>
        <option value="quant.">quant.*</option>
        <option value="user.">user.*</option>
      </select>
      <select
        v-model="minRisk"
        class="modern-select focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部风险分</option>
        <option value="40">中风险以上 (≥40)</option>
        <option value="60">高风险 (≥60)</option>
        <option value="80">极高风险 (≥80)</option>
      </select>
      <select
        v-model="severity"
        class="modern-select focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部级别</option>
        <option value="info">信息</option>
        <option value="warning">警告</option>
        <option value="critical">严重</option>
      </select>
      <select
        v-model="outcome"
        class="modern-select focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部结果</option>
        <option value="success">成功</option>
        <option value="failure">失败</option>
      </select>
      <div class="w-36">
        <BaseInput v-model="ipFilter" placeholder="精确 IP…" @keydown.enter="search" />
      </div>
      <BaseButton variant="secondary" @click="search">搜索</BaseButton>
      <BaseButton variant="ghost" :loading="loading" @click="load">
        <Icon name="refresh" :size="14" />
        刷新
      </BaseButton>
      <span v-if="data" class="ml-auto text-[13px] tabular-nums text-fg-faint">共 {{ data.total }} 条</span>
    </div>

    <p v-if="error" class="rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

    <div tabindex="0" role="region" aria-label="审计日志" class="table-wrapper focus-ring rounded-2xl border border-line bg-canvas">
      <table class="w-full min-w-[900px] text-sm">
        <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
          <tr>
            <th class="px-4 py-3 font-medium">时间</th>
            <th class="px-4 py-3 font-medium">操作者</th>
            <th class="px-4 py-3 font-medium">动作</th>
            <th class="px-4 py-3 font-medium">风险</th>
            <th class="px-4 py-3 font-medium">结果</th>
            <th class="px-4 py-3 font-medium">级别</th>
            <th class="px-4 py-3 font-medium">IP / Trace</th>
            <th class="px-4 py-3 text-right font-medium">详情</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-if="loading">
            <td colspan="8" class="px-4 py-12 text-center text-[13px] text-fg-faint">加载中…</td>
          </tr>
          <tr v-else-if="!data?.items.length">
            <td colspan="8" class="px-4 py-12 text-center text-[13px] text-fg-faint">暂无审计记录</td>
          </tr>
          <tr v-for="row in data?.items ?? []" :key="row.id" class="transition-colors hover:bg-surface">
            <td data-label="时间" class="whitespace-nowrap px-4 py-3 text-[12px] tabular-nums text-fg-faint">
              {{ fmtTime(row.created_at) }}
            </td>
            <td data-label="操作者" class="max-w-[170px] truncate px-4 py-3 text-[12px] text-fg-muted">
              {{ row.actor_email ?? "—" }}
            </td>
            <td data-label="动作" class="px-4 py-3">
              <div>
                <p class="font-mono text-[12px] text-fg">{{ row.action }}</p>
                <p v-if="row.target_type" class="mt-0.5 text-[10.5px] text-fg-faint">
                  {{ row.target_type }} · {{ row.target_id ?? "—" }}
                </p>
              </div>
            </td>
            <td data-label="风险" class="px-4 py-3">
              <BaseBadge :tone="riskTone(row.risk_score ?? 0)">{{ row.risk_score ?? 0 }}</BaseBadge>
            </td>
            <td data-label="结果" class="px-4 py-3">
              <BaseBadge :tone="row.outcome === 'success' ? 'green' : 'red'">
                {{ row.outcome === "success" ? "成功" : "失败" }}
              </BaseBadge>
            </td>
            <td data-label="级别" class="px-4 py-3">
              <BaseBadge :tone="severityTone(row)">{{ severityLabel(row) }}</BaseBadge>
            </td>
            <td data-label="IP" class="whitespace-nowrap px-4 py-3 text-[12px] tabular-nums text-fg-faint">
              <div>{{ row.ip ?? "—" }}</div>
              <button
                v-if="row.request_id"
                type="button"
                class="mt-0.5 font-mono text-[10.5px] text-accent hover:underline"
                @click="openTrace(row.request_id)"
              >
                req:{{ row.request_id.slice(0, 8) }}
              </button>
            </td>
            <td data-label="详情" class="px-4 py-3 text-right">
              <BaseButton size="sm" variant="ghost" @click="selected = row">查看</BaseButton>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="flex items-center justify-center gap-3">
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

    <!-- Detail Modal with Diff, Hash Fingerprint & Trace Shortcut -->
    <BaseModal :open="!!selected" title="审计详情与取证" width="44rem" @close="selected = null">
      <div v-if="selected" class="space-y-4">
        <dl class="grid grid-cols-[96px_1fr] gap-x-3 gap-y-2 text-[12.5px]">
          <dt class="text-fg-faint">记录 ID / 风险</dt>
          <dd class="flex items-center gap-2 text-fg">
            <span class="font-mono">#{{ selected.id }}</span>
            <BaseBadge :tone="riskTone(selected.risk_score ?? 0)">风险分 {{ selected.risk_score ?? 0 }}</BaseBadge>
          </dd>
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
          <dd class="flex flex-wrap items-center gap-2 break-all font-mono text-[11.5px] text-fg">
            <span>{{ selected.request_id ?? "—" }}</span>
            <BaseButton
              v-if="selected.request_id"
              size="sm"
              variant="secondary"
              @click="openTrace(selected.request_id)"
            >
              追踪同请求链路
            </BaseButton>
          </dd>
          <dt class="text-fg-faint">会话 ID</dt>
          <dd class="flex flex-wrap items-center gap-2 break-all font-mono text-[11.5px] text-fg">
            <span>{{ selected.session_id ?? "—" }}</span>
            <BaseButton
              v-if="selected.session_id"
              size="sm"
              variant="secondary"
              @click="openTrace(selected.session_id)"
            >
              追踪同会话事件
            </BaseButton>
          </dd>
          <dt class="text-fg-faint">链式指纹</dt>
          <dd class="space-y-0.5 break-all font-mono text-[10.5px] text-fg-muted">
            <p>curr: {{ selected.record_hash ?? "（旧记录未加链）" }}</p>
            <p>prev: {{ selected.prev_hash ?? "—" }}</p>
          </dd>
          <dt class="text-fg-faint">User-Agent</dt>
          <dd class="break-all text-[11.5px] text-fg-muted">{{ selected.user_agent ?? "—" }}</dd>
        </dl>

        <div v-if="selected.diff" class="grid gap-2 sm:grid-cols-2">
          <div>
            <p class="mb-1 text-[12px] font-medium text-fg-faint">变更前 (Before)</p>
            <pre class="mono-block max-h-48 overflow-auto rounded-xl border border-line bg-surface px-3 py-2 text-[11.5px] text-fg">{{
              JSON.stringify(selected.diff.before ?? null, null, 2)
            }}</pre>
          </div>
          <div>
            <p class="mb-1 text-[12px] font-medium text-fg-faint">变更后 (After)</p>
            <pre class="mono-block max-h-48 overflow-auto rounded-xl border border-line bg-surface px-3 py-2 text-[11.5px] text-fg">{{
              JSON.stringify(selected.diff.after ?? null, null, 2)
            }}</pre>
          </div>
        </div>

        <div v-if="selected.metadata">
          <p class="mb-1.5 text-[12px] text-fg-faint">附加信息</p>
          <pre class="mono-block max-h-48 overflow-auto rounded-xl border border-line bg-surface px-3 py-2.5 text-fg">{{
            JSON.stringify(selected.metadata, null, 2)
          }}</pre>
        </div>
      </div>
    </BaseModal>

    <!-- Trace Timeline Modal -->
    <BaseModal :open="traceOpen" title="关联链路时间线 (Trace)" width="42rem" @close="traceOpen = false">
      <div v-if="traceLoading" class="py-8 text-center text-[13px] text-fg-faint">正在聚合链路事件…</div>
      <div v-else-if="traceData" class="space-y-3">
        <p class="font-mono text-[12px] text-fg-muted">
          Trace ID: {{ traceData.trace_id }} · 共 {{ traceData.count }} 个节点
        </p>
        <div v-if="!traceData.items.length" class="py-6 text-center text-[13px] text-fg-faint">未找到关联记录</div>
        <div v-else class="space-y-2 border-l-2 border-line pl-4">
          <div v-for="item in traceData.items" :key="item.id" class="rounded-xl border border-line bg-surface p-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="font-mono text-[12.5px] font-medium text-fg">{{ item.action }}</span>
              <div class="flex items-center gap-1.5">
                <BaseBadge :tone="riskTone(item.risk_score ?? 0)">Risk {{ item.risk_score ?? 0 }}</BaseBadge>
                <BaseBadge :tone="item.outcome === 'success' ? 'green' : 'red'">{{ item.outcome }}</BaseBadge>
              </div>
            </div>
            <p class="mt-1 text-[11.5px] text-fg-faint">
              {{ fmtTime(item.created_at) }} · {{ item.actor_email ?? "system" }} · {{ item.target_type ?? "—" }} {{ item.target_id ?? "" }}
            </p>
          </div>
        </div>
      </div>
    </BaseModal>
  </div>
</template>
