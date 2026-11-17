<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api/client";
import { useAuthStore } from "../stores/auth";
import { useConversationsStore } from "../stores/conversations";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import ThemeToggle from "../components/ui/ThemeToggle.vue";
import PersonaEditor from "../components/settings/PersonaEditor.vue";
import MembershipPanel from "../components/settings/MembershipPanel.vue";

const auth = useAuthStore();
const conversations = useConversationsStore();
const router = useRouter();
const adminUrl = import.meta.env.VITE_ADMIN_URL;

function goBack() {
  const id = conversations.current?.id;
  if (id) {
    void router.push({ name: "chat-conversation", params: { id } });
  } else {
    void router.push({ name: "chat" });
  }
}

async function logout() {
  await auth.logout();
  await router.push("/login");
}

type Tab = "profile" | "membership" | "persona" | "password";
const tab = ref<Tab>("profile");
const tabs: { key: Tab; label: string; title: string; desc: string }[] = [
  { key: "profile", label: "个人资料", title: "个人资料", desc: "更新你的昵称与公开信息。" },
  { key: "membership", label: "会员与积分", title: "会员与积分", desc: "查看额度剩余、刷新时间并兑换邀请码。" },
  { key: "persona", label: "助理人设", title: "助理人设", desc: "定制助理的语气、角色与回答方式。" },
  { key: "password", label: "修改密码", title: "修改密码", desc: "修改后其他设备的登录将失效。" },
];
const activeMeta = () => tabs.find((t) => t.key === tab.value) ?? tabs[0];

// profile
const displayName = ref(auth.user?.display_name ?? "");
const profileMsg = ref<string | null>(null);
const profileErr = ref<string | null>(null);
const profileSaving = ref(false);
async function saveProfile() {
  profileSaving.value = true;
  profileMsg.value = null;
  profileErr.value = null;
  try {
    await api.patch("/users/me", { display_name: displayName.value.trim() });
    await auth.refreshUser();
    profileMsg.value = "已保存";
  } catch (e: any) {
    profileErr.value = e?.message ?? "保存失败";
  } finally {
    profileSaving.value = false;
  }
}

// password
const oldPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const pwdMsg = ref<string | null>(null);
const pwdErr = ref<string | null>(null);
const pwdSaving = ref(false);
async function savePassword() {
  pwdMsg.value = null;
  pwdErr.value = null;
  if (newPassword.value.length < 8) {
    pwdErr.value = "新密码至少 8 位";
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    pwdErr.value = "两次输入的新密码不一致";
    return;
  }
  pwdSaving.value = true;
  try {
    await api.put("/users/me/password", { old_password: oldPassword.value, new_password: newPassword.value });
    oldPassword.value = newPassword.value = confirmPassword.value = "";
    pwdMsg.value = "密码已修改，其他设备的登录已失效。";
  } catch (e: any) {
    pwdErr.value = e?.detail?.detail ?? "修改失败";
  } finally {
    pwdSaving.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-dvh flex-col bg-canvas">
    <header class="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3 sm:px-5">
      <button
        class="focus-ring -ml-1 flex h-9 w-9 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        aria-label="返回对话"
        @click="goBack"
      >
        <svg class="h-[18px] w-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
        </svg>
      </button>
      <h1 class="text-[16px] font-medium text-fg">设置</h1>
      <div class="ml-auto flex items-center gap-1.5">
        <a
          v-if="auth.isAdmin && adminUrl"
          :href="adminUrl"
          class="focus-ring inline-flex h-8.5 items-center rounded-lg px-2.5 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
        >
          管理后台
        </a>
        <ThemeToggle />
        <button
          type="button"
          class="focus-ring inline-flex h-8.5 items-center rounded-lg px-2.5 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-danger-weak hover:text-danger"
          @click="logout"
        >
          退出登录
        </button>
      </div>
    </header>

    <div class="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 py-6 sm:flex-row sm:px-6">
      <nav class="flex shrink-0 gap-1 overflow-x-auto no-scrollbar sm:w-52 sm:flex-col">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="focus-ring h-10 shrink-0 rounded-lg px-3.5 text-left text-[14.5px] font-medium transition-colors"
          :class="tab === t.key ? 'bg-surface text-fg' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @click="tab = t.key"
        >
          {{ t.label }}
        </button>
      </nav>

      <section class="min-w-0 flex-1">
        <div class="rounded-2xl border border-line bg-canvas p-5 sm:p-6">
          <div class="mb-5">
            <h2 class="text-[17px] font-semibold text-fg">{{ activeMeta().title }}</h2>
            <p class="mt-0.5 text-[14px] text-fg-muted">{{ activeMeta().desc }}</p>
          </div>

          <div v-if="tab === 'profile'" class="space-y-5">
            <div>
              <p class="mb-1.5 text-[14px] font-medium text-fg-muted">邮箱</p>
              <div class="flex items-center gap-2 rounded-xl bg-surface px-3.5 py-2.5">
                <span class="text-[15px] text-fg">{{ auth.user?.email }}</span>
                <BaseBadge v-if="auth.user?.email_verified_at" tone="green">已验证</BaseBadge>
                <BaseBadge v-if="auth.isAdmin" tone="brand">管理员</BaseBadge>
              </div>
            </div>
            <BaseInput v-model="displayName" label="昵称" />
            <p v-if="profileMsg" class="text-[14px] text-success">{{ profileMsg }}</p>
            <p v-if="profileErr" class="text-[14px] text-danger">{{ profileErr }}</p>
            <BaseButton :loading="profileSaving" @click="saveProfile">保存资料</BaseButton>
          </div>

          <div v-else-if="tab === 'membership'">
            <MembershipPanel />
          </div>

          <div v-else-if="tab === 'persona'">
            <PersonaEditor :persona="auth.user?.persona ?? ''" />
          </div>

          <div v-else-if="tab === 'password'" class="space-y-4">
            <BaseInput v-model="oldPassword" label="当前密码" type="password" autocomplete="current-password" />
            <BaseInput v-model="newPassword" label="新密码" type="password" placeholder="至少 8 位" autocomplete="new-password" />
            <BaseInput v-model="confirmPassword" label="确认新密码" type="password" autocomplete="new-password" />
            <p v-if="pwdMsg" class="text-[14px] text-success">{{ pwdMsg }}</p>
            <p v-if="pwdErr" class="text-[14px] text-danger">{{ pwdErr }}</p>
            <BaseButton :loading="pwdSaving" @click="savePassword">修改密码</BaseButton>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
