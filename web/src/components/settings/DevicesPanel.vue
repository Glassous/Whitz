<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../../api/client";
import type { UserSessionItem } from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseModal from "../ui/BaseModal.vue";
import FormError from "../ui/FormError.vue";
import Spinner from "../ui/Spinner.vue";

type DeviceKind = "desktop" | "mobile" | "tablet" | "unknown";

interface ParsedAgent {
  browser: string;
  os: string;
  kind: DeviceKind;
}

const sessions = ref<UserSessionItem[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const feedback = ref<string | null>(null);

const confirmTarget = ref<UserSessionItem | null>(null);
const confirmAllOpen = ref(false);
const revokingId = ref<string | null>(null);
const revokingAll = ref(false);
const modalError = ref<string | null>(null);

function extractError(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

function parseUserAgent(uaRaw: string | null | undefined): ParsedAgent {
  const ua = (uaRaw ?? "").trim();
  if (!ua) {
    return { browser: "未知浏览器", os: "未知系统", kind: "unknown" };
  }

  let kind: DeviceKind = "desktop";
  if (/iPad|Tablet|PlayBook|Silk/i.test(ua) || (/Android/i.test(ua) && !/Mobile/i.test(ua))) {
    kind = "tablet";
  } else if (/iPhone|iPod|Android.*Mobile|Windows Phone|BlackBerry|HarmonyOS|Mobile/i.test(ua)) {
    kind = "mobile";
  } else if (/Windows|Macintosh|Mac OS X|Linux|X11|CrOS/i.test(ua)) {
    kind = "desktop";
  } else {
    kind = "unknown";
  }

  let os = "未知系统";
  if (/iPhone|iPad|iPod/i.test(ua)) os = "iOS / iPadOS";
  else if (/HarmonyOS/i.test(ua)) os = "HarmonyOS";
  else if (/Android/i.test(ua)) os = "Android";
  else if (/Windows NT 10\.0|Windows NT 11\.0|Windows/i.test(ua)) os = "Windows";
  else if (/Macintosh|Mac OS X/i.test(ua)) os = "macOS";
  else if (/CrOS/i.test(ua)) os = "ChromeOS";
  else if (/Linux|X11/i.test(ua)) os = "Linux";

  let browser = "未知浏览器";
  if (/MicroMessenger/i.test(ua)) browser = "微信浏览器";
  else if (/DingTalk/i.test(ua)) browser = "钉钉";
  else if (/EdgA?|Edge\//i.test(ua)) browser = "Microsoft Edge";
  else if (/OPR\/|Opera/i.test(ua)) browser = "Opera";
  else if (/QQBrowser|MQQBrowser/i.test(ua)) browser = "QQ 浏览器";
  else if (/Firefox\/|FxiOS\//i.test(ua)) browser = "Firefox";
  else if (/Chrome\/|CriOS\//i.test(ua)) browser = "Chrome";
  else if (/Safari\//i.test(ua)) browser = "Safari";
  else if (/curl|python|httpx|axios|Postman/i.test(ua)) browser = "API 客户端";

  return { browser, os, kind };
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatRelative(value: string | null | undefined): string {
  if (!value) return "暂无记录";
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return "—";
  const diffMin = Math.floor((Date.now() - ts) / 60000);
  if (diffMin < 1) return "刚刚活跃";
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour} 小时前`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay} 天前`;
  return formatDateTime(value);
}

const sortedSessions = computed(() => {
  return [...sessions.value].sort((a, b) => {
    if (a.is_current !== b.is_current) return a.is_current ? -1 : 1;
    const ta = new Date(a.last_used_at ?? a.created_at).getTime();
    const tb = new Date(b.last_used_at ?? b.created_at).getTime();
    return tb - ta;
  });
});

const otherSessionsCount = computed(() => sessions.value.filter((s) => !s.is_current).length);

async function loadSessions() {
  loading.value = true;
  error.value = null;
  try {
    const data = await api.get<UserSessionItem[]>("/users/me/sessions");
    sessions.value = Array.isArray(data) ? data : [];
  } catch (e: any) {
    error.value = extractError(e, "加载登录设备失败");
  } finally {
    loading.value = false;
  }
}

function requestRevokeOne(session: UserSessionItem) {
  modalError.value = null;
  confirmTarget.value = session;
}

function requestRevokeOthers() {
  modalError.value = null;
  confirmAllOpen.value = true;
}

async function confirmRevokeOne() {
  const target = confirmTarget.value;
  if (!target) return;
  revokingId.value = target.session_id;
  modalError.value = null;
  feedback.value = null;
  try {
    await api.delete(`/users/me/sessions/${encodeURIComponent(target.session_id)}`);
    sessions.value = sessions.value.filter((s) => s.session_id !== target.session_id);
    confirmTarget.value = null;
    feedback.value = "已将该设备下线";
  } catch (e: any) {
    modalError.value = extractError(e, "下线设备失败");
  } finally {
    revokingId.value = null;
  }
}

async function confirmRevokeOthers() {
  revokingAll.value = true;
  modalError.value = null;
  feedback.value = null;
  try {
    await api.delete("/users/me/sessions?exclude_current=true");
    sessions.value = sessions.value.filter((s) => s.is_current);
    confirmAllOpen.value = false;
    feedback.value = "已退出其他所有设备的登录会话";
  } catch (e: any) {
    modalError.value = extractError(e, "退出其他设备失败");
  } finally {
    revokingAll.value = false;
  }
}

onMounted(() => {
  void loadSessions();
});
</script>

<template>
  <div class="space-y-5">
    <!-- Overview & Bulk Action Card -->
    <section class="flex flex-col gap-3 rounded-[24px] bg-sidebar p-5 sm:flex-row sm:items-center sm:justify-between dark:bg-surface">
      <div class="min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="text-[15.5px] font-semibold text-fg">活跃登录会话</h2>
          <BaseBadge tone="gray">{{ sessions.length }} 台设备</BaseBadge>
        </div>
        <p class="mt-1 text-[13px] text-fg-muted">
          管理已登录当前账号的浏览器与终端设备。下线设备后，其访问令牌与刷新会话将立即失效。
        </p>
      </div>

      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <BaseButton variant="soft" size="sm" rounded="full" :disabled="loading" @click="loadSessions">
          刷新
        </BaseButton>
        <BaseButton
          variant="danger"
          size="sm"
          rounded="full"
          :disabled="loading || otherSessionsCount === 0"
          @click="requestRevokeOthers"
        >
          退出其他所有设备 ({{ otherSessionsCount }})
        </BaseButton>
      </div>
    </section>

    <FormError :message="error" />
    <div
      v-if="feedback"
      role="status"
      aria-live="polite"
      class="rounded-2xl bg-success-weak px-4 py-2.5 text-[13px] text-success"
    >
      {{ feedback }}
    </div>

    <!-- Loading -->
    <div
      v-if="loading && !sessions.length"
      class="flex items-center justify-center gap-2.5 rounded-[24px] bg-sidebar py-12 text-[13.5px] text-fg-muted dark:bg-surface"
    >
      <Spinner :size="18" />
      <span>正在加载登录设备…</span>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!sessions.length"
      class="rounded-[24px] bg-sidebar px-6 py-10 text-center text-[13.5px] text-fg-muted dark:bg-surface"
    >
      暂无活跃登录会话记录。
    </div>

    <!-- Session Cards -->
    <div v-else class="space-y-3">
      <article
        v-for="session in sortedSessions"
        :key="session.session_id"
        class="flex flex-col gap-3 rounded-[24px] bg-sidebar p-5 transition-colors sm:flex-row sm:items-center sm:justify-between dark:bg-surface"
        :class="session.is_current ? 'ring-1 ring-accent/45' : ''"
      >
        <div class="flex min-w-0 items-start gap-3.5">
          <!-- Device Icon -->
          <span
            class="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-canvas text-fg dark:bg-active"
            aria-hidden="true"
          >
            <!-- Mobile -->
            <svg
              v-if="parseUserAgent(session.user_agent).kind === 'mobile'"
              class="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
            >
              <rect x="7" y="2.5" width="10" height="19" rx="2.2" />
              <path stroke-linecap="round" d="M11 18.5h2" />
            </svg>
            <!-- Tablet -->
            <svg
              v-else-if="parseUserAgent(session.user_agent).kind === 'tablet'"
              class="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
            >
              <rect x="4.5" y="3" width="15" height="18" rx="2" />
              <path stroke-linecap="round" d="M11 18h2" />
            </svg>
            <!-- Desktop -->
            <svg
              v-else-if="parseUserAgent(session.user_agent).kind === 'desktop'"
              class="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
            >
              <rect x="3" y="4" width="18" height="12" rx="2" />
              <path stroke-linecap="round" d="M2 20h20" />
            </svg>
            <!-- Unknown -->
            <svg
              v-else
              class="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
            >
              <circle cx="12" cy="12" r="9" />
              <path stroke-linecap="round" d="M3.5 9h17M3.5 15h17M12 3a14 14 0 010 18M12 3a14 14 0 000 18" />
            </svg>
          </span>

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-[14.5px] font-semibold text-fg">
                {{ parseUserAgent(session.user_agent).browser }} · {{ parseUserAgent(session.user_agent).os }}
              </h3>
              <BaseBadge v-if="session.is_current" tone="green">当前设备</BaseBadge>
            </div>

            <div class="mt-1.5 grid grid-cols-1 gap-x-5 gap-y-1 text-[12.5px] text-fg-muted sm:grid-cols-2 lg:flex lg:flex-wrap">
              <span class="tabular-nums">IP：{{ session.client_ip || "未知" }}</span>
              <span class="tabular-nums">最近活跃：{{ formatRelative(session.last_used_at ?? session.created_at) }}</span>
              <span class="tabular-nums">登录时间：{{ formatDateTime(session.created_at) }}</span>
            </div>

            <p
              v-if="session.user_agent"
              class="mt-1 truncate text-[11.5px] text-fg-faint"
              :title="session.user_agent"
            >
              {{ session.user_agent }}
            </p>
          </div>
        </div>

        <div class="flex shrink-0 items-center justify-end gap-2">
          <span v-if="session.is_current" class="text-[12px] font-medium text-fg-faint">正在使用</span>
          <BaseButton
            v-else
            variant="secondary"
            size="sm"
            rounded="full"
            :loading="revokingId === session.session_id"
            @click="requestRevokeOne(session)"
          >
            下线此设备
          </BaseButton>
        </div>
      </article>
    </div>

    <!-- Single Session Revoke Confirmation -->
    <BaseModal
      :open="!!confirmTarget"
      title="下线设备"
      @close="confirmTarget = null"
    >
      <div v-if="confirmTarget" class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          确定要下线
          <strong class="font-medium text-fg">
            {{ parseUserAgent(confirmTarget.user_agent).browser }} · {{ parseUserAgent(confirmTarget.user_agent).os }}
          </strong>
          （IP：{{ confirmTarget.client_ip || "未知" }}）吗？下线后该设备需重新登录。
        </p>
        <FormError :message="modalError" />
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="!!revokingId" @click="confirmTarget = null">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="!!revokingId" @click="confirmRevokeOne">
          确认下线
        </BaseButton>
      </template>
    </BaseModal>

    <!-- Revoke All Other Devices Confirmation -->
    <BaseModal
      :open="confirmAllOpen"
      title="退出其他所有设备"
      @close="confirmAllOpen = false"
    >
      <div class="space-y-3">
        <p class="text-[14px] leading-relaxed text-fg-muted">
          确定要强制退出除当前设备外的全部 <strong class="font-medium text-fg">{{ otherSessionsCount }}</strong> 台设备吗？这些设备的活跃会话将立即失效。
        </p>
        <FormError :message="modalError" />
      </div>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="revokingAll" @click="confirmAllOpen = false">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="revokingAll" @click="confirmRevokeOthers">
          确认退出其他设备
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
