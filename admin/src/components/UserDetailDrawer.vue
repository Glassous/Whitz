<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from "vue";
import { api, readableError } from "../api/client";
import type {
  AdminLedgerItem,
  AdminLedgerList,
  AdminUser,
  AdminUserDetail,
  MembershipTier,
  UserSession,
} from "../types";
import BaseBadge from "./ui/BaseBadge.vue";
import BaseButton from "./ui/BaseButton.vue";
import BaseModal from "./ui/BaseModal.vue";
import Icon from "./ui/Icon.vue";

type DrawerTab = "ledger" | "sessions" | "redemptions";
type LedgerKindFilter = "all" | "consume" | "adjust";

const props = defineProps<{
  userId: string | null;
  refreshKey?: number;
}>();

const emit = defineEmits<{
  close: [];
  editMembership: [user: AdminUser];
  editCredits: [user: AdminUser];
}>();

const titleId = useId();
const dialogRef = ref<HTMLDialogElement | null>(null);
const rendered = ref(Boolean(props.userId));
let pressedOutside = false;

let supportsDisplayTransition: boolean | undefined;
function canTransitionDisplay(): boolean {
  if (supportsDisplayTransition !== undefined) return supportsDisplayTransition;
  if (!window.CSS?.supports?.("transition-behavior", "allow-discrete") || !document.body) {
    return false;
  }
  const probe = document.createElement("div");
  probe.style.cssText = "transition: display 1s allow-discrete !important; display: block;";
  document.body.appendChild(probe);
  getComputedStyle(probe).display;
  probe.style.display = "none";
  supportsDisplayTransition = getComputedStyle(probe).display === "block";
  probe.remove();
  return supportsDisplayTransition;
}

function supportsTopLayerExit(): boolean {
  return Boolean(window.CSS?.supports?.("overlay", "auto") && canTransitionDisplay());
}

function isOutside(e: PointerEvent, dialog: HTMLDialogElement): boolean {
  const r = dialog.getBoundingClientRect();
  return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
}

async function openDialog() {
  rendered.value = true;
  await nextTick();
  const dialog = dialogRef.value;
  if (dialog && !dialog.open) {
    dialog.removeAttribute("data-closing");
    dialog.showModal();
  }
}

async function closeDialog() {
  const dialog = dialogRef.value;
  if (!dialog || !dialog.open) {
    rendered.value = false;
    return;
  }
  if (!supportsTopLayerExit()) {
    dialog.setAttribute("data-closing", "");
    const animations = dialog.getAnimations({ subtree: true });
    if (animations.length > 0) {
      await Promise.race([
        Promise.allSettled(animations.map((a) => a.finished)),
        new Promise((r) => setTimeout(r, 400)),
      ]);
    }
    if (!dialog.hasAttribute("data-closing")) return;
    dialog.removeAttribute("data-closing");
  }
  if (dialog.open) dialog.close();
  rendered.value = false;
}

function onCancel(e: Event) {
  e.preventDefault();
  if (kickTarget.value) return;
  emit("close");
}

function onNativeClose() {
  if (props.userId) emit("close");
  rendered.value = false;
}

function onPointerdown(e: PointerEvent) {
  const dialog = dialogRef.value;
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  pressedOutside = e.target === dialog && isOutside(e, dialog);
}

function onPointerup(e: PointerEvent) {
  const dialog = dialogRef.value;
  if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
  if (pressedOutside && e.target === dialog && isOutside(e, dialog)) emit("close");
  pressedOutside = false;
}

const activeTab = ref<DrawerTab>("ledger");
const detail = ref<AdminUserDetail | null>(null);
const loadingDetail = ref(false);
const detailError = ref<string | null>(null);

const ledger = ref<AdminLedgerList | null>(null);
const ledgerPage = ref(1);
const ledgerPageSize = 15;
const ledgerKind = ref<LedgerKindFilter>("all");
const loadingLedger = ref(false);
const ledgerError = ref<string | null>(null);

const sessions = ref<UserSession[]>([]);
const loadingSessions = ref(false);
const sessionsError = ref<string | null>(null);
const kickTarget = ref<UserSession | null>(null);
const kickLoading = ref(false);
const kickError = ref<string | null>(null);

let loadSeq = 0;
let ledgerSeq = 0;
let sessionsSeq = 0;

const numberFormat = new Intl.NumberFormat("zh-CN");

const ledgerTotalPages = computed(() =>
  ledger.value ? Math.max(1, Math.ceil(ledger.value.total / ledgerPageSize)) : 1,
);

const initials = computed(() => {
  const u = detail.value;
  return (u?.display_name || u?.email || "?").slice(0, 1).toUpperCase();
});

function fmt(n: number): string {
  return numberFormat.format(n);
}

function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

function tierLabel(tier: MembershipTier | string): string {
  const normalized = tier.toLowerCase();
  if (normalized === "pro") return "Pro";
  if (normalized === "plus") return "Plus";
  return "Free";
}

function tierTone(tier: MembershipTier | string): "brand" | "blue" | "gray" {
  const normalized = tier.toLowerCase();
  if (normalized === "pro") return "brand";
  if (normalized === "plus") return "blue";
  return "gray";
}

function signedCredits(value: number): string {
  const rounded = Number.isInteger(value) ? value.toString() : value.toFixed(2).replace(/\.?0+$/, "");
  return value > 0 ? `+${rounded}` : rounded;
}

function signedTokens(value: number): string {
  const formatted = numberFormat.format(value);
  return value > 0 ? `+${formatted}` : formatted;
}

function kindLabel(kind: AdminLedgerItem["kind"]): string {
  if (kind === "consume") return "消耗";
  if (kind === "adjust") return "调整";
  return kind;
}

function describeAgent(ua: string | null): string {
  if (!ua) return "未知设备";
  const lower = ua.toLowerCase();
  const browser = lower.includes("edg/")
    ? "Edge"
    : lower.includes("chrome/") && !lower.includes("chromium")
      ? "Chrome"
      : lower.includes("firefox/")
        ? "Firefox"
        : lower.includes("safari/") && !lower.includes("chrome/")
          ? "Safari"
          : lower.includes("curl")
            ? "cURL"
            : "浏览器";
  const os = lower.includes("iphone") || lower.includes("ipad")
    ? "iOS"
    : lower.includes("android")
      ? "Android"
      : lower.includes("windows")
        ? "Windows"
        : lower.includes("mac os") || lower.includes("macintosh")
          ? "macOS"
          : lower.includes("linux")
            ? "Linux"
            : "未知系统";
  return `${browser} · ${os}`;
}

function safeWebsiteUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("https://") || url.startsWith("http://") ? url : null;
}

async function fetchDetail(uid: string, seq: number) {
  loadingDetail.value = true;
  detailError.value = null;
  try {
    const res = await api.get<AdminUserDetail>(`/admin/users/${uid}`);
    if (seq !== loadSeq) return;
    detail.value = res;
  } catch (e: unknown) {
    if (seq !== loadSeq) return;
    detailError.value = readableError(e);
  } finally {
    if (seq === loadSeq) loadingDetail.value = false;
  }
}

async function fetchLedger(uid: string) {
  const seq = ++ledgerSeq;
  loadingLedger.value = true;
  ledgerError.value = null;
  try {
    const params = new URLSearchParams({
      page: String(ledgerPage.value),
      page_size: String(ledgerPageSize),
    });
    if (ledgerKind.value !== "all") params.set("kind", ledgerKind.value);
    const res = await api.get<AdminLedgerList>(`/admin/users/${uid}/ledger?${params.toString()}`);
    if (seq !== ledgerSeq) return;
    ledger.value = res;
  } catch (e: unknown) {
    if (seq !== ledgerSeq) return;
    ledgerError.value = readableError(e);
  } finally {
    if (seq === ledgerSeq) loadingLedger.value = false;
  }
}

async function fetchSessions(uid: string) {
  const seq = ++sessionsSeq;
  loadingSessions.value = true;
  sessionsError.value = null;
  try {
    const res = await api.get<UserSession[]>(`/admin/users/${uid}/sessions`);
    if (seq !== sessionsSeq) return;
    sessions.value = res;
  } catch (e: unknown) {
    if (seq !== sessionsSeq) return;
    sessionsError.value = readableError(e);
  } finally {
    if (seq === sessionsSeq) loadingSessions.value = false;
  }
}

async function loadAll(uid: string) {
  const seq = ++loadSeq;
  await Promise.all([fetchDetail(uid, seq), fetchLedger(uid), fetchSessions(uid)]);
}

function setLedgerKind(kind: LedgerKindFilter) {
  if (ledgerKind.value === kind) return;
  ledgerKind.value = kind;
  ledgerPage.value = 1;
  if (props.userId) void fetchLedger(props.userId);
}

function goLedgerPage(next: number) {
  ledgerPage.value = next;
  if (props.userId) void fetchLedger(props.userId);
}

function openKickModal(session: UserSession) {
  kickError.value = null;
  kickTarget.value = session;
}

async function confirmKickSession() {
  const uid = props.userId;
  const target = kickTarget.value;
  if (!uid || !target) return;
  kickLoading.value = true;
  kickError.value = null;
  try {
    await api.delete(`/admin/users/${uid}/sessions/${target.session_id}`);
    kickTarget.value = null;
    await Promise.all([fetchSessions(uid), fetchDetail(uid, ++loadSeq)]);
  } catch (e: unknown) {
    kickError.value = readableError(e);
  } finally {
    kickLoading.value = false;
  }
}

watch(
  () => props.userId,
  (uid, prev) => {
    if (uid) {
      if (uid !== prev) {
        activeTab.value = "ledger";
        ledgerKind.value = "all";
        ledgerPage.value = 1;
        detail.value = null;
        ledger.value = null;
        sessions.value = [];
      }
      void openDialog();
      void loadAll(uid);
    } else {
      kickTarget.value = null;
      void closeDialog();
    }
  },
);

watch(
  () => props.refreshKey,
  () => {
    if (props.userId) {
      void loadAll(props.userId);
    }
  },
);

onMounted(() => {
  if (props.userId) {
    void openDialog();
    void loadAll(props.userId);
  }
});
</script>

<template>
  <dialog
    ref="dialogRef"
    class="user-drawer"
    closedby="any"
    :aria-labelledby="titleId"
    @cancel="onCancel"
    @close="onNativeClose"
    @pointerdown="onPointerdown"
    @pointerup="onPointerup"
  >
    <div v-if="rendered" class="flex h-full flex-col bg-canvas text-fg">
      <header class="flex shrink-0 items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div class="flex min-w-0 items-center gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface text-[14px] font-semibold text-fg">
            {{ initials }}
          </div>
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-1.5">
              <h2 :id="titleId" class="truncate text-[15px] font-semibold text-fg">
                {{ detail?.display_name ?? "用户详情" }}
              </h2>
              <BaseBadge v-if="detail" :tone="detail.role === 'admin' ? 'brand' : 'gray'">
                {{ detail.role === "admin" ? "管理员" : "用户" }}
              </BaseBadge>
              <BaseBadge v-if="detail" :tone="detail.is_active ? 'green' : 'red'">
                {{ detail.is_active ? "启用" : "禁用" }}
              </BaseBadge>
              <BaseBadge v-if="detail" :tone="tierTone(detail.membership_tier)">
                {{ tierLabel(detail.membership_tier) }}
              </BaseBadge>
            </div>
            <p class="truncate text-[12px] text-fg-faint">{{ detail?.email ?? userId }}</p>
          </div>
        </div>

        <div class="flex shrink-0 items-center gap-1">
          <BaseButton
            v-if="userId"
            size="sm"
            variant="ghost"
            :loading="loadingDetail || loadingLedger || loadingSessions"
            @click="loadAll(userId)"
          >
            <Icon name="refresh" :size="14" />
            刷新
          </BaseButton>
          <button
            type="button"
            class="focus-ring rounded-lg p-1.5 text-fg-faint transition-colors hover:bg-hover hover:text-fg"
            aria-label="关闭"
            @click="emit('close')"
          >
            <Icon name="close" :size="18" />
          </button>
        </div>
      </header>

      <div class="flex-1 overflow-y-auto px-5 py-4">
        <p v-if="detailError" class="mb-4 rounded-xl bg-danger-weak px-3 py-2 text-[12.5px] text-danger">
          {{ detailError }}
        </p>

        <div v-if="loadingDetail && !detail" class="rounded-2xl border border-line px-4 py-16 text-center text-[13px] text-fg-faint">
          加载用户详情中…
        </div>

        <div v-else-if="detail" class="space-y-5">
          <!-- Quick Actions & Credit Snapshot -->
          <section class="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface/40 p-4">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[12px] text-fg-muted">当前剩余积分</span>
                <span class="text-[18px] font-semibold tabular-nums text-fg">
                  {{ detail.credits ? detail.credits.remaining.toFixed(1) : "—" }}
                </span>
                <BaseBadge v-if="detail.credits?.overdrawn" tone="red">已透支</BaseBadge>
              </div>
              <p v-if="detail.credits" class="mt-1 text-[11.5px] tabular-nums text-fg-faint">
                周用量 {{ detail.credits.weekly_used }} / {{ detail.credits.weekly_limit }} · 5 小时
                {{ detail.credits.five_hour_used }} / {{ detail.credits.five_hour_limit ?? "∞" }}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <BaseButton size="sm" variant="secondary" @click="emit('editMembership', detail)">调整会员</BaseButton>
              <BaseButton size="sm" variant="primary" @click="emit('editCredits', detail)">调整积分</BaseButton>
            </div>
          </section>

          <!-- Privacy / Memory Consent Badges -->
          <section class="rounded-2xl border border-line bg-canvas p-4">
            <h3 class="text-[12.5px] font-medium text-fg-muted">隐私与记忆授权</h3>
            <div class="mt-2.5 flex flex-wrap gap-2">
              <BaseBadge :tone="detail.profile_context_enabled ? 'green' : 'gray'">
                画像上下文：{{ detail.profile_context_enabled ? "已授权开启" : "未开启" }}
              </BaseBadge>
              <BaseBadge :tone="detail.memory_enabled ? 'green' : 'gray'">
                长期记忆：{{ detail.memory_enabled ? "已授权开启" : "未开启" }}
              </BaseBadge>
              <BaseBadge :tone="detail.memory_require_confirm ? 'brand' : 'amber'">
                {{ detail.memory_require_confirm ? "记忆写入需用户确认" : "记忆自动写入" }}
              </BaseBadge>
            </div>
            <div
              v-if="detail.profile_context_consented_at || detail.memory_consented_at"
              class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] tabular-nums text-fg-faint"
            >
              <span v-if="detail.profile_context_consented_at">
                画像授权时间：{{ fmtTime(detail.profile_context_consented_at) }}
              </span>
              <span v-if="detail.memory_consented_at">
                记忆授权时间：{{ fmtTime(detail.memory_consented_at) }}
              </span>
            </div>
          </section>

          <!-- Usage Totals -->
          <section class="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div class="rounded-xl border border-line bg-canvas px-3 py-2.5">
              <p class="text-[11px] text-fg-faint">会话数</p>
              <p class="mt-1 text-[18px] font-semibold tabular-nums text-fg">{{ fmt(detail.conversation_count) }}</p>
            </div>
            <div class="rounded-xl border border-line bg-canvas px-3 py-2.5">
              <p class="text-[11px] text-fg-faint">消息数</p>
              <p class="mt-1 text-[18px] font-semibold tabular-nums text-fg">{{ fmt(detail.message_count) }}</p>
              <p class="mt-0.5 text-[10.5px] tabular-nums text-fg-faint">日统计 {{ fmt(detail.total_messages) }}</p>
            </div>
            <div class="rounded-xl border border-line bg-canvas px-3 py-2.5">
              <p class="text-[11px] text-fg-faint">工作区文件</p>
              <p class="mt-1 text-[18px] font-semibold tabular-nums text-fg">{{ fmt(detail.file_count) }}</p>
            </div>
            <div class="rounded-xl border border-line bg-canvas px-3 py-2.5">
              <p class="text-[11px] text-fg-faint">累计 Token</p>
              <p class="mt-1 text-[18px] font-semibold tabular-nums text-fg">{{ fmt(detail.total_tokens) }}</p>
              <p class="mt-0.5 text-[10.5px] tabular-nums text-fg-faint">运行 {{ fmt(detail.total_runs) }} 次</p>
            </div>
          </section>

          <!-- Profile Info -->
          <section class="rounded-2xl border border-line bg-canvas p-4">
            <h3 class="text-[12.5px] font-medium text-fg-muted">账号与资料信息</h3>
            <dl class="mt-3 grid grid-cols-1 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-2">
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">Hermes Profile</dt>
                <dd class="truncate font-mono text-[11.5px] text-fg">{{ detail.hermes_profile }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">语言 / 时区</dt>
                <dd class="truncate text-fg">{{ detail.preferred_language || "—" }} · {{ detail.timezone || "—" }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">会员有效期</dt>
                <dd class="tabular-nums text-fg">{{ fmtTime(detail.membership_expires_at) }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">注册时间</dt>
                <dd class="tabular-nums text-fg">{{ fmtTime(detail.created_at) }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">邮箱验证</dt>
                <dd class="tabular-nums text-fg">{{ fmtTime(detail.email_verified_at) }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">手机 / 地区</dt>
                <dd class="truncate text-fg">{{ detail.phone || "—" }} · {{ detail.location || "—" }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">职业 / 性别</dt>
                <dd class="truncate text-fg">{{ detail.occupation || "—" }} · {{ detail.gender || "—" }}</dd>
              </div>
              <div class="flex items-baseline justify-between gap-2 border-b border-line/60 pb-1.5">
                <dt class="shrink-0 text-fg-faint">生日 / 个人主页</dt>
                <dd class="truncate text-fg">
                  {{ fmtDate(detail.birthday) }} ·
                  <a
                    v-if="safeWebsiteUrl(detail.website)"
                    :href="safeWebsiteUrl(detail.website)!"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-accent hover:underline"
                  >
                    {{ detail.website }}
                  </a>
                  <span v-else>{{ detail.website || "—" }}</span>
                </dd>
              </div>
            </dl>
            <div v-if="detail.bio" class="mt-2.5 rounded-xl bg-surface px-3 py-2 text-[12px] text-fg-muted">
              {{ detail.bio }}
            </div>
          </section>

          <!-- Tabs -->
          <section class="overflow-hidden rounded-2xl border border-line bg-canvas">
            <div class="flex items-center gap-1 border-b border-line bg-surface/50 px-3 py-2">
              <button
                type="button"
                class="focus-ring rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors"
                :class="activeTab === 'ledger' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
                @click="activeTab = 'ledger'"
              >
                积分流水
                <span v-if="ledger" class="ml-1 text-[11px] tabular-nums text-fg-faint">{{ ledger.total }}</span>
              </button>
              <button
                type="button"
                class="focus-ring rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors"
                :class="activeTab === 'sessions' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
                @click="activeTab = 'sessions'"
              >
                登录设备
                <span class="ml-1 text-[11px] tabular-nums text-fg-faint">{{ sessions.length }}</span>
              </button>
              <button
                type="button"
                class="focus-ring rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors"
                :class="activeTab === 'redemptions' ? 'bg-canvas text-fg shadow-xs' : 'text-fg-muted hover:text-fg'"
                @click="activeTab = 'redemptions'"
              >
                兑换记录
                <span class="ml-1 text-[11px] tabular-nums text-fg-faint">{{ detail.invite_redemptions.length }}</span>
              </button>
            </div>

            <!-- Tab 1: Credit Ledger -->
            <div v-if="activeTab === 'ledger'" class="p-4">
              <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div class="inline-flex rounded-xl border border-line bg-surface p-0.5">
                  <button
                    v-for="opt in ([
                      { key: 'all', label: '全部' },
                      { key: 'consume', label: '消耗' },
                      { key: 'adjust', label: '管理员调整' },
                    ] as const)"
                    :key="opt.key"
                    type="button"
                    class="focus-ring rounded-lg px-2.5 py-1 text-[11.5px] font-medium transition-colors"
                    :class="ledgerKind === opt.key ? 'bg-canvas text-fg' : 'text-fg-muted hover:text-fg'"
                    @click="setLedgerKind(opt.key)"
                  >
                    {{ opt.label }}
                  </button>
                </div>
                <span v-if="ledger" class="text-[11.5px] tabular-nums text-fg-faint">共 {{ ledger.total }} 条</span>
              </div>

              <p v-if="ledgerError" class="mb-3 rounded-xl bg-danger-weak px-3 py-2 text-[12px] text-danger">
                {{ ledgerError }}
              </p>

              <div class="overflow-x-auto rounded-xl border border-line">
                <table class="w-full min-w-[540px] text-left text-[12px]">
                  <thead class="bg-surface text-[11px] text-fg-faint">
                    <tr>
                      <th class="px-3 py-2 font-medium">时间</th>
                      <th class="px-3 py-2 font-medium">类型</th>
                      <th class="px-3 py-2 text-right font-medium">积分</th>
                      <th class="px-3 py-2 text-right font-medium">Tokens</th>
                      <th class="px-3 py-2 font-medium">操作人 / 备注</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-line">
                    <tr v-if="loadingLedger">
                      <td colspan="5" class="px-3 py-8 text-center text-fg-faint">加载中…</td>
                    </tr>
                    <tr v-else-if="!ledger?.items.length">
                      <td colspan="5" class="px-3 py-8 text-center text-fg-faint">暂无积分流水</td>
                    </tr>
                    <tr v-for="item in ledger?.items ?? []" :key="item.id" class="hover:bg-surface/60">
                      <td class="whitespace-nowrap px-3 py-2 tabular-nums text-fg-faint">
                        {{ fmtTime(item.created_at) }}
                      </td>
                      <td class="px-3 py-2">
                        <BaseBadge :tone="item.kind === 'adjust' ? 'brand' : 'gray'">
                          {{ kindLabel(item.kind) }}
                        </BaseBadge>
                      </td>
                      <td
                        class="whitespace-nowrap px-3 py-2 text-right font-medium tabular-nums"
                        :class="item.credits > 0 ? 'text-success' : item.credits < 0 ? 'text-fg' : 'text-fg-faint'"
                      >
                        {{ signedCredits(item.credits) }}
                      </td>
                      <td class="whitespace-nowrap px-3 py-2 text-right tabular-nums text-fg-muted">
                        {{ signedTokens(item.tokens) }}
                      </td>
                      <td class="max-w-[200px] px-3 py-2">
                        <p class="truncate text-fg-muted">{{ item.actor_email ?? "系统" }}</p>
                        <p v-if="item.note" class="truncate text-[11px] text-fg-faint">{{ item.note }}</p>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div v-if="ledger && ledger.total > ledgerPageSize" class="mt-3 flex items-center justify-center gap-3">
                <BaseButton
                  size="sm"
                  variant="secondary"
                  :disabled="ledgerPage <= 1 || loadingLedger"
                  @click="goLedgerPage(ledgerPage - 1)"
                >
                  <Icon name="chevron-left" :size="14" />
                  上一页
                </BaseButton>
                <span class="text-[12px] tabular-nums text-fg-muted">{{ ledgerPage }} / {{ ledgerTotalPages }}</span>
                <BaseButton
                  size="sm"
                  variant="secondary"
                  :disabled="ledgerPage >= ledgerTotalPages || loadingLedger"
                  @click="goLedgerPage(ledgerPage + 1)"
                >
                  下一页
                  <Icon name="chevron-right" :size="14" />
                </BaseButton>
              </div>
            </div>

            <!-- Tab 2: Active Sessions / Devices -->
            <div v-else-if="activeTab === 'sessions'" class="p-4">
              <div class="mb-3 flex items-center justify-between gap-2">
                <p class="text-[12px] text-fg-faint">当前有效登录会话，踢出后对应设备会立即失效。</p>
                <BaseButton
                  v-if="userId"
                  size="sm"
                  variant="ghost"
                  :loading="loadingSessions"
                  @click="fetchSessions(userId)"
                >
                  <Icon name="refresh" :size="13" />
                  刷新
                </BaseButton>
              </div>

              <p v-if="sessionsError" class="mb-3 rounded-xl bg-danger-weak px-3 py-2 text-[12px] text-danger">
                {{ sessionsError }}
              </p>

              <div v-if="loadingSessions && !sessions.length" class="py-10 text-center text-[12.5px] text-fg-faint">
                加载设备列表中…
              </div>
              <div v-else-if="!sessions.length" class="rounded-xl border border-line py-10 text-center text-[12.5px] text-fg-faint">
                当前没有活跃登录设备
              </div>
              <div v-else class="space-y-2.5">
                <div
                  v-for="s in sessions"
                  :key="s.session_id"
                  class="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-line bg-canvas p-3"
                >
                  <div class="min-w-0 flex-1">
                    <div class="flex flex-wrap items-center gap-1.5">
                      <Icon name="device" :size="14" class="text-fg-muted" />
                      <span class="text-[12.5px] font-medium text-fg">{{ describeAgent(s.user_agent) }}</span>
                      <BaseBadge v-if="s.is_current" tone="green">当前会话</BaseBadge>
                      <span class="text-[11.5px] tabular-nums text-fg-faint">{{ s.client_ip ?? "未知 IP" }}</span>
                    </div>
                    <p v-if="s.user_agent" class="mt-1 break-all font-mono text-[10.5px] text-fg-faint">
                      {{ s.user_agent }}
                    </p>
                    <div class="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] tabular-nums text-fg-muted">
                      <span>最近活跃：{{ fmtTime(s.last_used_at) }}</span>
                      <span>登录：{{ fmtTime(s.created_at) }}</span>
                      <span>过期：{{ fmtTime(s.expires_at) }}</span>
                    </div>
                  </div>
                  <BaseButton size="sm" variant="danger" @click="openKickModal(s)">踢出下线</BaseButton>
                </div>
              </div>
            </div>

            <!-- Tab 3: Invite Redemptions -->
            <div v-else class="p-4">
              <div class="overflow-x-auto rounded-xl border border-line">
                <table class="w-full min-w-[460px] text-left text-[12px]">
                  <thead class="bg-surface text-[11px] text-fg-faint">
                    <tr>
                      <th class="px-3 py-2 font-medium">邀请码</th>
                      <th class="px-3 py-2 font-medium">档位</th>
                      <th class="px-3 py-2 font-medium">时长</th>
                      <th class="px-3 py-2 font-medium">兑换时间</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-line">
                    <tr v-if="!detail.invite_redemptions.length">
                      <td colspan="4" class="px-3 py-8 text-center text-fg-faint">暂无邀请码兑换记录</td>
                    </tr>
                    <tr v-for="r in detail.invite_redemptions" :key="r.id" class="hover:bg-surface/60">
                      <td class="px-3 py-2 font-mono text-fg">{{ r.code ?? r.code_id }}</td>
                      <td class="px-3 py-2">
                        <BaseBadge :tone="tierTone(r.tier)">{{ tierLabel(r.tier) }}</BaseBadge>
                      </td>
                      <td class="px-3 py-2 tabular-nums text-fg-muted">{{ r.duration_days }} 天</td>
                      <td class="whitespace-nowrap px-3 py-2 tabular-nums text-fg-faint">
                        {{ fmtTime(r.redeemed_at) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  </dialog>

  <BaseModal :open="!!kickTarget" title="踢出登录设备" width="26rem" @close="kickTarget = null">
    <p class="text-[13px] leading-relaxed text-fg-muted">
      确认强制下线设备
      <span class="font-medium text-fg">{{ kickTarget ? describeAgent(kickTarget.user_agent) : "" }}</span>
      （IP: <span class="tabular-nums text-fg">{{ kickTarget?.client_ip ?? "未知" }}</span>）？该设备的当前登录凭证将立即失效。
    </p>
    <p v-if="kickError" class="mt-2 rounded-xl bg-danger-weak px-3 py-2 text-[12px] text-danger">{{ kickError }}</p>
    <template #footer>
      <BaseButton variant="secondary" @click="kickTarget = null">取消</BaseButton>
      <BaseButton variant="danger" :loading="kickLoading" @click="confirmKickSession">确认踢出</BaseButton>
    </template>
  </BaseModal>
</template>

<style scoped>
dialog.user-drawer {
  margin: 0 0 0 auto;
  padding: 0;
  border: none;
  border-left: 1px solid var(--line);
  background: var(--canvas);
  color: var(--fg);
  width: min(100dvw, 46rem);
  max-width: 100dvw;
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  opacity: 0;
  transition-property: opacity, transform, display, overlay;
  transition-duration: 0.2s;
  transition-timing-function: cubic-bezier(0.22, 1, 0.36, 1);
  transition-behavior: allow-discrete;
}

@media (prefers-reduced-motion: no-preference) {
  dialog.user-drawer {
    transform: translateX(24px);
  }
}

dialog.user-drawer[open]:where(:not([data-closing])) {
  opacity: 1;

  @starting-style {
    opacity: 0;
  }

  @media (prefers-reduced-motion: no-preference) {
    transform: translateX(0);

    @starting-style {
      transform: translateX(24px);
    }
  }
}

dialog.user-drawer:modal {
  overscroll-behavior: contain;
}

dialog.user-drawer::backdrop {
  background-color: rgb(0 0 0 / 0);
  backdrop-filter: blur(2px);
  transition-property: background-color, display, overlay;
  transition-duration: 0.2s;
  transition-timing-function: ease-out;
  transition-behavior: allow-discrete;
}

dialog.user-drawer[open]:where(:not([data-closing]))::backdrop {
  background-color: rgb(0 0 0 / 0.4);

  @starting-style {
    background-color: rgb(0 0 0 / 0);
  }
}

:global(.dark) dialog.user-drawer[open]:where(:not([data-closing]))::backdrop {
  background-color: rgb(0 0 0 / 0.6);

  @starting-style {
    background-color: rgb(0 0 0 / 0);
  }
}

@media (prefers-reduced-motion: reduce) {
  dialog.user-drawer,
  dialog.user-drawer::backdrop {
    transition-duration: 0.08s;
  }
}
</style>
