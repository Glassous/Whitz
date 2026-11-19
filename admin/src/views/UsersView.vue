<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, readableError } from "../api/client";
import { useAuthStore } from "../stores/auth";
import type { AdminUser, AdminUserList, CreditSummary, MembershipTier } from "../types";
import UserAccessModals from "../components/UserAccessModals.vue";
import UserDetailDrawer from "../components/UserDetailDrawer.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import Icon from "../components/ui/Icon.vue";

const auth = useAuthStore();

const data = ref<AdminUserList | null>(null);
const query = ref("");
const role = ref("");
const status = ref("");
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const error = ref<string | null>(null);
const pendingId = ref<string | null>(null);

const disableTarget = ref<AdminUser | null>(null);
const confirmLoading = ref(false);

const memberTarget = ref<AdminUser | null>(null);
const creditTarget = ref<AdminUser | null>(null);
const detailUserId = ref<string | null>(null);
const drawerRefreshKey = ref(0);

const totalPages = computed(() => (data.value ? Math.max(1, Math.ceil(data.value.total / pageSize)) : 1));

function tierLabel(tier: MembershipTier): string {
  return tier === "pro" ? "Pro" : tier === "plus" ? "Plus" : "Free";
}

function tierTone(tier: MembershipTier): "brand" | "blue" | "gray" {
  return tier === "pro" ? "brand" : tier === "plus" ? "blue" : "gray";
}

function creditPercent(c: CreditSummary): number {
  const limit = c.weekly_limit;
  if (!limit) return 0;
  return Math.max(0, Math.min(100, Math.round((c.remaining / limit) * 100)));
}

function creditTone(c: CreditSummary): string {
  if (c.overdrawn) return "bg-danger";
  const percent = creditPercent(c);
  return percent <= 20 ? "bg-warning" : "bg-accent";
}

function openMembership(user: AdminUser) {
  memberTarget.value = user;
}

function openCredits(user: AdminUser) {
  creditTarget.value = user;
}

function openDetail(user: AdminUser) {
  detailUserId.value = user.id;
}

function handleAccessSaved() {
  drawerRefreshKey.value += 1;
  void load();
}

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize) });
    if (query.value.trim()) params.set("q", query.value.trim());
    if (role.value) params.set("role", role.value);
    if (status.value) params.set("is_active", status.value);
    data.value = await api.get<AdminUserList>(`/admin/users?${params.toString()}`);
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

async function changeRole(user: AdminUser, nextRole: "user" | "admin") {
  if (user.role === nextRole) return;
  pendingId.value = user.id;
  error.value = null;
  try {
    await api.patch(`/admin/users/${user.id}`, { role: nextRole });
    await load();
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    pendingId.value = null;
  }
}

async function setActive(user: AdminUser, active: boolean) {
  pendingId.value = user.id;
  error.value = null;
  try {
    await api.patch(`/admin/users/${user.id}`, { is_active: active });
    await load();
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    pendingId.value = null;
  }
}

function askDisable(user: AdminUser) {
  disableTarget.value = user;
}

async function confirmDisable() {
  const target = disableTarget.value;
  if (!target) return;
  confirmLoading.value = true;
  await setActive(target, false);
  confirmLoading.value = false;
  disableTarget.value = null;
}

onMounted(load);
</script>

<template>
  <div>
    <div class="mb-6">
      <h1 class="text-[20px] font-semibold tracking-tight text-fg">用户</h1>
      <p class="mt-1 text-[12px] text-fg-faint">管理账号状态与管理员权限</p>
    </div>

    <div class="mb-4 flex flex-wrap items-center gap-2">
      <div class="w-full sm:w-72">
        <BaseInput v-model="query" placeholder="搜索邮箱或昵称…" @keydown.enter="search" />
      </div>
      <select
        v-model="role"
        class="modern-select focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部角色</option>
        <option value="user">用户</option>
        <option value="admin">管理员</option>
      </select>
      <select
        v-model="status"
        class="modern-select focus-ring h-11 rounded-xl border border-line bg-canvas px-3 text-[13px] text-fg"
        @change="search"
      >
        <option value="">全部状态</option>
        <option value="true">启用</option>
        <option value="false">禁用</option>
      </select>
      <BaseButton variant="secondary" @click="search">搜索</BaseButton>
      <span v-if="data" class="ml-auto text-[13px] tabular-nums text-fg-faint">共 {{ data.total }} 位用户</span>
    </div>

    <p v-if="error" class="mb-3 rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>

    <div tabindex="0" role="region" aria-label="用户列表" class="table-wrapper focus-ring rounded-2xl border border-line bg-canvas">
      <table class="w-full min-w-[980px] text-sm">
        <thead class="bg-surface text-left text-[11px] uppercase tracking-wide text-fg-faint">
          <tr>
            <th class="px-4 py-3 font-medium">用户</th>
            <th class="px-4 py-3 font-medium">角色</th>
            <th class="px-4 py-3 font-medium">会员</th>
            <th class="px-4 py-3 font-medium">积分</th>
            <th class="px-4 py-3 font-medium">状态</th>
            <th class="px-4 py-3 font-medium">注册时间</th>
            <th class="px-4 py-3 text-right font-medium">操作</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-line">
          <tr v-if="loading">
            <td colspan="7" class="px-4 py-12 text-center text-[13px] text-fg-faint">加载中…</td>
          </tr>
          <tr v-else-if="!data?.items.length">
            <td colspan="7" class="px-4 py-12 text-center text-[13px] text-fg-faint">没有匹配的用户</td>
          </tr>
          <tr v-for="u in data?.items ?? []" :key="u.id" class="transition-colors hover:bg-surface">
            <td data-label="用户" class="px-4 py-3">
              <div>
                <p class="text-[13px] font-medium text-fg">{{ u.display_name }}</p>
                <p class="text-xs text-fg-faint">{{ u.email }}</p>
                <p class="mt-0.5 truncate font-mono text-[10.5px] text-fg-faint" title="Agent 命名空间">{{ u.agent_namespace }}</p>
              </div>
            </td>
            <td data-label="角色" class="px-4 py-3">
              <select
                :value="u.role"
                :disabled="u.id === auth.user?.id || pendingId === u.id"
                class="modern-select focus-ring h-8 rounded-lg border border-line bg-canvas px-2 text-xs text-fg disabled:opacity-50"
                @change="changeRole(u, ($event.target as HTMLSelectElement).value as 'user' | 'admin')"
              >
                <option value="user">用户</option>
                <option value="admin">管理员</option>
              </select>
            </td>
            <td data-label="会员" class="px-4 py-3">
              <div>
                <BaseBadge :tone="tierTone(u.membership_tier)">{{ tierLabel(u.membership_tier) }}</BaseBadge>
                <p class="mt-0.5 whitespace-nowrap text-[11px] text-fg-faint">
                  {{ u.membership_expires_at ? "至 " + new Date(u.membership_expires_at).toLocaleDateString() : "—" }}
                </p>
              </div>
            </td>
            <td data-label="积分" class="px-4 py-3">
              <div>
                <p class="text-[12px] tabular-nums text-fg">
                  {{ u.credits ? u.credits.remaining.toFixed(1) : "—" }}
                  <span class="text-[10.5px] text-fg-faint">积分</span>
                </p>
                <div v-if="u.credits" class="mt-1 h-1 w-20 overflow-hidden rounded-full bg-surface">
                  <div
                    class="h-full rounded-full transition-[width] duration-300"
                    :class="creditTone(u.credits)"
                    :style="{ width: `${creditPercent(u.credits)}%` }"
                  />
                </div>
                <p v-if="u.credits" class="mt-0.5 text-[10.5px] tabular-nums text-fg-faint">
                  周 {{ u.credits.weekly_used }}/{{ u.credits.weekly_limit }}
                </p>
                <p v-if="u.credits" class="text-[10.5px] tabular-nums text-fg-faint">
                  5h {{ u.credits.five_hour_used }}/{{ u.credits.five_hour_limit ?? "∞" }}
                </p>
              </div>
            </td>
            <td data-label="状态" class="px-4 py-3">
              <BaseBadge :tone="u.is_active ? 'green' : 'red'">{{ u.is_active ? "启用" : "禁用" }}</BaseBadge>
            </td>
            <td data-label="注册时间" class="whitespace-nowrap px-4 py-3 text-[12px] tabular-nums text-fg-faint">
              {{ new Date(u.created_at).toLocaleDateString() }}
            </td>
            <td data-label="操作" class="px-4 py-3 text-right">
              <div class="flex items-center justify-end gap-1 whitespace-nowrap">
                <BaseButton size="sm" variant="secondary" @click="openDetail(u)">详情</BaseButton>
                <BaseButton size="sm" variant="ghost" @click="openMembership(u)">会员</BaseButton>
                <BaseButton size="sm" variant="ghost" @click="openCredits(u)">积分</BaseButton>
                <BaseButton
                  v-if="u.id !== auth.user?.id"
                  size="sm"
                  :variant="u.is_active ? 'danger' : 'primary'"
                  :loading="pendingId === u.id"
                  @click="u.is_active ? askDisable(u) : setActive(u, true)"
                >
                  {{ u.is_active ? "禁用" : "启用" }}
                </BaseButton>
                <span v-else class="px-1 text-[11px] text-fg-faint">当前账号</span>
              </div>
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

    <BaseModal :open="!!disableTarget" title="禁用账号" width="26rem" @close="disableTarget = null">
      <p class="text-[13px] leading-relaxed text-fg-muted">
        禁用后
        <span class="font-medium text-fg">{{ disableTarget?.display_name }}</span>
        将立即退出所有设备，且无法再次登录。Agent 配置会进入休眠，但数据保留。
      </p>
      <template #footer>
        <BaseButton variant="secondary" @click="disableTarget = null">取消</BaseButton>
        <BaseButton variant="danger" :loading="confirmLoading" @click="confirmDisable">确认禁用</BaseButton>
      </template>
    </BaseModal>

    <UserDetailDrawer
      :user-id="detailUserId"
      :refresh-key="drawerRefreshKey"
      @close="detailUserId = null"
      @edit-membership="openMembership"
      @edit-credits="openCredits"
    />

    <UserAccessModals
      :member-target="memberTarget"
      :credit-target="creditTarget"
      @close-member="memberTarget = null"
      @close-credit="creditTarget = null"
      @saved="handleAccessSaved"
    />
  </div>
</template>
