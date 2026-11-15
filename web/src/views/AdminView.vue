<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api/client";
import { useAuthStore } from "../stores/auth";
import type { AdminUser, AdminUserList, AuditLog, AuditLogList } from "../types";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import ThemeToggle from "../components/ui/ThemeToggle.vue";

const auth = useAuthStore();
const router = useRouter();

const tab = ref<"users" | "audit">("users");
const data = ref<AdminUserList | null>(null);
const query = ref("");
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const error = ref<string | null>(null);

const auditData = ref<AuditLogList | null>(null);
const auditQuery = ref("");
const auditSeverity = ref("");
const auditPage = ref(1);
const auditPageSize = 50;
const auditLoading = ref(false);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) });
    if (query.value.trim()) params.set("q", query.value.trim());
    data.value = await api.get<AdminUserList>(`/admin/users?${params.toString()}`);
  } catch (e: any) {
    error.value = e?.message ?? "加载失败";
  } finally {
    loading.value = false;
  }
}

function search() {
  page.value = 1;
  void load();
}

async function loadAudit() {
  auditLoading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams({
      page: String(auditPage.value),
      page_size: String(auditPageSize),
    });
    if (auditQuery.value.trim()) params.set("q", auditQuery.value.trim());
    if (auditSeverity.value) params.set("severity", auditSeverity.value);
    auditData.value = await api.get<AuditLogList>(`/admin/audit-logs?${params.toString()}`);
  } catch (e: any) {
    error.value = e?.message ?? "加载失败";
  } finally {
    auditLoading.value = false;
  }
}

function searchAudit() {
  auditPage.value = 1;
  void loadAudit();
}

function switchTab(next: "users" | "audit") {
  tab.value = next;
  error.value = null;
  if (next === "audit" && !auditData.value) void loadAudit();
}

async function setActive(user: AdminUser, active: boolean) {
  error.value = null;
  try {
    await api.patch(`/admin/users/${user.id}`, { is_active: active });
    await load();
  } catch (e: any) {
    error.value = e?.detail?.detail ?? "操作失败";
  }
}

async function setRole(user: AdminUser, role: "user" | "admin") {
  error.value = null;
  try {
    await api.patch(`/admin/users/${user.id}`, { role });
    await load();
  } catch (e: any) {
    error.value = e?.detail?.detail ?? "操作失败";
  }
}

const totalPages = () => (data.value ? Math.max(1, Math.ceil(data.value.total / pageSize)) : 1);
const auditTotalPages = () =>
  auditData.value ? Math.max(1, Math.ceil(auditData.value.total / auditPageSize)) : 1;

const severityTone = (row: AuditLog) =>
  row.severity === "critical" ? "red" : row.severity === "warning" ? "amber" : "gray";

const severityLabel = (row: AuditLog) =>
  row.severity === "critical" ? "严重" : row.severity === "warning" ? "警告" : "信息";

const outcomeLabel = (row: AuditLog) => (row.outcome === "success" ? "成功" : "失败");

onMounted(load);
</script>

<template>
  <div class="flex min-h-dvh flex-col bg-canvas">
    <header class="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3 sm:px-5">
      <button
        class="focus-ring -ml-1 flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        aria-label="返回对话"
        @click="router.push('/')"
      >
        <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
        </svg>
      </button>
      <h1 class="text-[14px] font-medium text-fg">管理员后台</h1>
      <BaseBadge tone="brand">{{ tab === "users" ? "用户管理" : "审计日志" }}</BaseBadge>
      <div class="ml-auto"><ThemeToggle /></div>
    </header>

    <div class="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6">
      <div class="mb-4 inline-flex rounded-xl border border-line bg-surface p-0.5">
        <button
          class="focus-ring rounded-[10px] px-3 py-1.5 text-[13px] transition-colors"
          :class="tab === 'users' ? 'bg-canvas text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
          @click="switchTab('users')"
        >
          用户
        </button>
        <button
          class="focus-ring rounded-[10px] px-3 py-1.5 text-[13px] transition-colors"
          :class="tab === 'audit' ? 'bg-canvas text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
          @click="switchTab('audit')"
        >
          审计日志
        </button>
      </div>

      <template v-if="tab === 'users'">
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <div class="w-full sm:w-72">
            <BaseInput v-model="query" placeholder="搜索邮箱或昵称…" @keydown.enter="search" />
          </div>
          <BaseButton variant="secondary" @click="search">搜索</BaseButton>
          <span v-if="data" class="ml-auto text-[13px] text-fg-faint">共 {{ data.total }} 位用户</span>
        </div>

        <p v-if="error" class="mb-3 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

        <div class="overflow-x-auto rounded-2xl border border-line bg-canvas">
          <table class="w-full min-w-[620px] text-sm">
            <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
              <tr>
                <th class="px-4 py-3 font-medium">用户</th>
                <th class="px-4 py-3 font-medium">角色</th>
                <th class="px-4 py-3 font-medium">状态</th>
                <th class="px-4 py-3 font-medium">注册时间</th>
                <th class="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-if="loading">
                <td colspan="5" class="px-4 py-10 text-center text-[13px] text-fg-faint">加载中…</td>
              </tr>
              <tr v-else-if="!data?.items.length">
                <td colspan="5" class="px-4 py-10 text-center text-[13px] text-fg-faint">没有匹配的用户</td>
              </tr>
              <tr v-for="u in data?.items ?? []" :key="u.id" class="transition-colors hover:bg-surface">
                <td class="px-4 py-3">
                  <p class="text-[13px] font-medium text-fg">{{ u.display_name }}</p>
                  <p class="text-xs text-fg-faint">{{ u.email }}</p>
                </td>
                <td class="px-4 py-3">
                  <select
                    :value="u.role"
                    :disabled="u.id === auth.user?.id"
                    class="focus-ring h-8 rounded-lg border border-line bg-canvas px-2 text-xs text-fg disabled:opacity-50"
                    @change="setRole(u, ($event.target as HTMLSelectElement).value as 'user' | 'admin')"
                  >
                    <option value="user">用户</option>
                    <option value="admin">管理员</option>
                  </select>
                </td>
                <td class="px-4 py-3">
                  <BaseBadge :tone="u.is_active ? 'green' : 'red'">{{ u.is_active ? "启用" : "禁用" }}</BaseBadge>
                </td>
                <td class="px-4 py-3 text-[12px] tabular-nums text-fg-faint">
                  {{ new Date(u.created_at).toLocaleDateString() }}
                </td>
                <td class="px-4 py-3 text-right">
                  <BaseButton
                    v-if="u.id !== auth.user?.id"
                    size="sm"
                    :variant="u.is_active ? 'danger' : 'primary'"
                    @click="setActive(u, !u.is_active)"
                  >
                    {{ u.is_active ? "禁用" : "启用" }}
                  </BaseButton>
                  <span v-else class="text-xs text-fg-faint">当前账号</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 flex items-center justify-center gap-3">
          <BaseButton size="sm" variant="secondary" :disabled="page <= 1" @click="page--; load()">上一页</BaseButton>
          <span class="text-[13px] tabular-nums text-fg-muted">{{ page }} / {{ totalPages() }}</span>
          <BaseButton size="sm" variant="secondary" :disabled="page >= totalPages()" @click="page++; load()">下一页</BaseButton>
        </div>
      </template>

      <template v-else>
        <div class="mb-4 flex flex-wrap items-center gap-2">
          <div class="w-full sm:w-72">
            <BaseInput v-model="auditQuery" placeholder="搜索邮箱、动作或对象 ID…" @keydown.enter="searchAudit" />
          </div>
          <select
            v-model="auditSeverity"
            class="focus-ring h-10 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
            @change="searchAudit"
          >
            <option value="">全部级别</option>
            <option value="info">信息</option>
            <option value="warning">警告</option>
            <option value="critical">严重</option>
          </select>
          <BaseButton variant="secondary" @click="searchAudit">搜索</BaseButton>
          <BaseButton variant="ghost" @click="loadAudit">刷新</BaseButton>
          <span v-if="auditData" class="ml-auto text-[13px] text-fg-faint">共 {{ auditData.total }} 条</span>
        </div>

        <p v-if="error" class="mb-3 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

        <div class="overflow-x-auto rounded-2xl border border-line bg-canvas">
          <table class="w-full min-w-[760px] text-sm">
            <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
              <tr>
                <th class="px-4 py-3 font-medium">时间</th>
                <th class="px-4 py-3 font-medium">操作者</th>
                <th class="px-4 py-3 font-medium">动作</th>
                <th class="px-4 py-3 font-medium">结果</th>
                <th class="px-4 py-3 font-medium">级别</th>
                <th class="px-4 py-3 font-medium">IP</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-if="auditLoading">
                <td colspan="6" class="px-4 py-10 text-center text-[13px] text-fg-faint">加载中…</td>
              </tr>
              <tr v-else-if="!auditData?.items.length">
                <td colspan="6" class="px-4 py-10 text-center text-[13px] text-fg-faint">暂无审计记录</td>
              </tr>
              <tr v-for="row in auditData?.items ?? []" :key="row.id" class="transition-colors hover:bg-surface">
                <td class="whitespace-nowrap px-4 py-3 text-[12px] tabular-nums text-fg-faint">
                  {{ new Date(row.created_at).toLocaleString() }}
                </td>
                <td class="px-4 py-3 text-[12px] text-fg-muted">{{ row.actor_email ?? "—" }}</td>
                <td class="px-4 py-3 text-[12px] text-fg">{{ row.action }}</td>
                <td class="px-4 py-3">
                  <BaseBadge :tone="row.outcome === 'success' ? 'green' : 'red'">{{ outcomeLabel(row) }}</BaseBadge>
                </td>
                <td class="px-4 py-3">
                  <BaseBadge :tone="severityTone(row)">{{ severityLabel(row) }}</BaseBadge>
                </td>
                <td class="px-4 py-3 text-[12px] tabular-nums text-fg-faint">{{ row.ip ?? "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-4 flex items-center justify-center gap-3">
          <BaseButton size="sm" variant="secondary" :disabled="auditPage <= 1" @click="auditPage--; loadAudit()">上一页</BaseButton>
          <span class="text-[13px] tabular-nums text-fg-muted">{{ auditPage }} / {{ auditTotalPages() }}</span>
          <BaseButton
            size="sm"
            variant="secondary"
            :disabled="auditPage >= auditTotalPages()"
            @click="auditPage++; loadAudit()"
          >
            下一页
          </BaseButton>
        </div>
      </template>
    </div>
  </div>
</template>
