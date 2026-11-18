<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api/client";
import { useTheme, type ThemePreference } from "../lib/theme";
import { useAuthStore } from "../stores/auth";
import { useConversationsStore } from "../stores/conversations";
import { useCreditsStore } from "../stores/credits";
import BaseButton from "../components/ui/BaseButton.vue";
import BaseBadge from "../components/ui/BaseBadge.vue";
import BaseModal from "../components/ui/BaseModal.vue";
import PersonaEditor from "../components/settings/PersonaEditor.vue";
import MembershipPanel from "../components/settings/MembershipPanel.vue";
import AvatarCropModal from "../components/settings/AvatarCropModal.vue";

type SettingsPage = "profile" | "membership" | "persona" | "password";

const auth = useAuthStore();
const conversations = useConversationsStore();
const credits = useCreditsStore();
const router = useRouter();
const { preference, set: setTheme } = useTheme();
const adminUrl = import.meta.env.VITE_ADMIN_URL;

const activePage = ref<SettingsPage>("profile");
const mobileAtRoot = ref(true);
const isDesktop = ref(typeof window !== "undefined" ? window.innerWidth >= 768 : true);
let mediaQuery: MediaQueryList | null = null;

function onMediaChange(e: MediaQueryListEvent) {
  isDesktop.value = e.matches;
}

onMounted(() => {
  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(min-width: 768px)");
    isDesktop.value = mediaQuery.matches;
    mediaQuery.addEventListener("change", onMediaChange);
  }
  void credits.fetch();
});

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener("change", onMediaChange);
});

const showMobileMenu = computed(() => !isDesktop.value && mobileAtRoot.value);

function selectMainPage(page: "profile" | "membership" | "persona") {
  activePage.value = page;
  mobileAtRoot.value = false;
}

function openPasswordPage() {
  activePage.value = "password";
  mobileAtRoot.value = false;
}

function goBackFromMobilePage() {
  if (activePage.value === "password") {
    activePage.value = "profile";
  } else {
    mobileAtRoot.value = true;
  }
}

const themeOptions: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

const navItems: { key: "profile" | "membership" | "persona"; label: string; desc: string }[] = [
  { key: "profile", label: "用户信息", desc: "头像、个人资料与账号安全" },
  { key: "membership", label: "会员与额度", desc: "当前档位、用量与兑换码" },
  { key: "persona", label: "助理人设", desc: "定制语气、角色与回答方式" },
];

const pageTitle = computed(() => {
  if (activePage.value === "password") return "修改密码";
  return navItems.find((n) => n.key === activePage.value)?.label ?? "用户信息";
});

const initials = computed(() => {
  const name = auth.user?.display_name?.trim();
  if (name) return Array.from(name)[0]?.toUpperCase() ?? "U";
  return auth.user?.email?.slice(0, 1).toUpperCase() ?? "U";
});

const joinedAt = computed(() => {
  if (!auth.user?.created_at) return "—";
  return new Date(auth.user.created_at).toLocaleDateString();
});

const tierBadgeClass = computed(() => {
  if (credits.tier === "pro") return "bg-primary text-primary-fg";
  if (credits.tier === "plus") return "bg-active text-fg";
  return "bg-surface text-fg-muted";
});

function goBackToChat() {
  const id = conversations.current?.id;
  if (id) {
    void router.push({ name: "chat-conversation", params: { id } });
  } else {
    void router.push({ name: "chat" });
  }
}

const logoutModalOpen = ref(false);
const loggingOut = ref(false);

async function confirmLogout() {
  loggingOut.value = true;
  try {
    await auth.logout();
    await router.push("/login");
  } finally {
    loggingOut.value = false;
    logoutModalOpen.value = false;
  }
}

// Avatar upload & 1:1 crop
const avatarFileInput = ref<HTMLInputElement | null>(null);
const cropModalOpen = ref(false);
const pendingAvatarFile = ref<File | null>(null);
const avatarLoadFailed = ref(false);
const avatarDeleting = ref(false);
const avatarFeedback = ref<string | null>(null);

watch(
  () => auth.user?.avatar_url,
  () => {
    avatarLoadFailed.value = false;
  },
);

function triggerAvatarPick() {
  avatarFeedback.value = null;
  avatarFileInput.value?.click();
}

function onAvatarFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  input.value = "";
  if (!file) return;
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    avatarFeedback.value = "请选择 PNG、JPEG 或 WebP 格式的图片";
    return;
  }
  pendingAvatarFile.value = file;
  cropModalOpen.value = true;
}

function onAvatarUploaded() {
  avatarFeedback.value = "头像已更新";
}

async function removeAvatar() {
  avatarFeedback.value = null;
  avatarDeleting.value = true;
  try {
    await api.delete("/users/me/avatar");
    await auth.refreshUser();
    avatarFeedback.value = "已移除头像";
  } catch (e: any) {
    avatarFeedback.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "移除失败");
  } finally {
    avatarDeleting.value = false;
  }
}

// Profile fields
const PRESET_GENDERS = ["", "男", "女", "保密"] as const;
const languageOptions = [
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁體中文" },
  { value: "en-US", label: "English" },
  { value: "ja-JP", label: "日本語" },
];
const timezoneOptions = [
  { value: "Asia/Shanghai", label: "中国标准时间 (UTC+8)" },
  { value: "Asia/Tokyo", label: "东京 (UTC+9)" },
  { value: "Asia/Singapore", label: "新加坡 (UTC+8)" },
  { value: "Europe/London", label: "伦敦 (UTC+0/+1)" },
  { value: "America/New_York", label: "纽约 (UTC-5/-4)" },
  { value: "America/Los_Angeles", label: "洛杉矶 (UTC-8/-7)" },
  { value: "UTC", label: "协调世界时 (UTC)" },
];

const displayName = ref(auth.user?.display_name ?? "");
const genderSelect = ref<string>("");
const customGender = ref("");
const birthday = ref(auth.user?.birthday ?? "");
const occupation = ref(auth.user?.occupation ?? "");
const location = ref(auth.user?.location ?? "");
const phone = ref(auth.user?.phone ?? "");
const website = ref(auth.user?.website ?? "");
const preferredLanguage = ref(auth.user?.preferred_language || "zh-CN");
const timezone = ref(auth.user?.timezone || "Asia/Shanghai");
const bio = ref(auth.user?.bio ?? "");

const profileDirty = ref(false);
const profileMsg = ref<string | null>(null);
const profileErr = ref<string | null>(null);
const profileInvalidField = ref<"displayName" | "phone" | "website" | null>(null);
const profileSaving = ref(false);

const displayNameInput = ref<HTMLInputElement | null>(null);
const phoneInput = ref<HTMLInputElement | null>(null);
const websiteInput = ref<HTMLInputElement | null>(null);

function syncGenderFromUser(raw: string | null | undefined) {
  const val = (raw ?? "").trim();
  if (!val) {
    genderSelect.value = "";
    customGender.value = "";
  } else if ((PRESET_GENDERS as readonly string[]).includes(val)) {
    genderSelect.value = val;
    customGender.value = "";
  } else {
    genderSelect.value = "__custom__";
    customGender.value = val;
  }
}

syncGenderFromUser(auth.user?.gender);

watch(
  () => auth.user,
  (u) => {
    if (u && !profileDirty.value) {
      displayName.value = u.display_name ?? "";
      syncGenderFromUser(u.gender);
      birthday.value = u.birthday ?? "";
      occupation.value = u.occupation ?? "";
      location.value = u.location ?? "";
      phone.value = u.phone ?? "";
      website.value = u.website ?? "";
      preferredLanguage.value = u.preferred_language || "zh-CN";
      timezone.value = u.timezone || "Asia/Shanghai";
      bio.value = u.bio ?? "";
    }
  },
);

function onProfileInput() {
  profileDirty.value = true;
  profileErr.value = null;
  profileMsg.value = null;
  profileInvalidField.value = null;
}

const resolvedGender = computed(() => {
  if (genderSelect.value === "__custom__") return customGender.value.trim();
  return genderSelect.value;
});

async function saveProfile() {
  profileMsg.value = null;
  profileErr.value = null;
  profileInvalidField.value = null;

  const trimmedName = displayName.value.trim();
  const trimmedPhone = phone.value.trim();
  const trimmedWebsite = website.value.trim();

  if (!trimmedName) {
    profileErr.value = "请输入用户名";
    profileInvalidField.value = "displayName";
    displayNameInput.value?.focus();
    return;
  }
  if (trimmedName.includes("@")) {
    profileErr.value = "用户名不能包含 @ 符号";
    profileInvalidField.value = "displayName";
    displayNameInput.value?.focus();
    return;
  }
  if (trimmedPhone && !/^[+\d\s\-()]{5,32}$/.test(trimmedPhone)) {
    profileErr.value = "请输入有效的联系电话";
    profileInvalidField.value = "phone";
    phoneInput.value?.focus();
    return;
  }
  if (trimmedWebsite && !(trimmedWebsite.startsWith("https://") || trimmedWebsite.startsWith("http://"))) {
    profileErr.value = "个人主页需以 http:// 或 https:// 开头";
    profileInvalidField.value = "website";
    websiteInput.value?.focus();
    return;
  }

  profileSaving.value = true;
  try {
    await api.patch("/users/me", {
      display_name: trimmedName,
      gender: resolvedGender.value || null,
      birthday: birthday.value || null,
      occupation: occupation.value.trim() || null,
      location: location.value.trim() || null,
      phone: trimmedPhone || null,
      website: trimmedWebsite || null,
      preferred_language: preferredLanguage.value || "zh-CN",
      timezone: timezone.value || "Asia/Shanghai",
      bio: bio.value.trim(),
    });
    await auth.refreshUser();
    displayName.value = trimmedName;
    phone.value = trimmedPhone;
    website.value = trimmedWebsite;
    occupation.value = occupation.value.trim();
    location.value = location.value.trim();
    bio.value = bio.value.trim();
    profileDirty.value = false;
    profileMsg.value = "个人资料已保存";
  } catch (e: any) {
    profileErr.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "保存失败");
    displayNameInput.value?.focus();
  } finally {
    profileSaving.value = false;
  }
}

// Password sub-page
const oldPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const showPasswords = ref(false);
const pwdMsg = ref<string | null>(null);
const pwdErr = ref<string | null>(null);
const pwdInvalidField = ref<"old" | "new" | "confirm" | null>(null);
const pwdSaving = ref(false);

const oldPwdInput = ref<HTMLInputElement | null>(null);
const newPwdInput = ref<HTMLInputElement | null>(null);
const confirmPwdInput = ref<HTMLInputElement | null>(null);

function clearPasswordError() {
  pwdErr.value = null;
  pwdMsg.value = null;
  pwdInvalidField.value = null;
}

function validateNewPasswordBlur() {
  if (newPassword.value && newPassword.value.length < 8) {
    pwdErr.value = "新密码至少需要 8 位字符";
    pwdInvalidField.value = "new";
  }
}

function validateConfirmPasswordBlur() {
  if (confirmPassword.value && newPassword.value && confirmPassword.value !== newPassword.value) {
    pwdErr.value = "两次输入的新密码不一致";
    pwdInvalidField.value = "confirm";
  }
}

async function savePassword() {
  pwdMsg.value = null;
  pwdErr.value = null;
  pwdInvalidField.value = null;

  if (!oldPassword.value) {
    pwdErr.value = "请输入当前密码";
    pwdInvalidField.value = "old";
    oldPwdInput.value?.focus();
    return;
  }
  if (newPassword.value.length < 8) {
    pwdErr.value = "新密码至少需要 8 位字符";
    pwdInvalidField.value = "new";
    newPwdInput.value?.focus();
    return;
  }
  if (newPassword.value !== confirmPassword.value) {
    pwdErr.value = "两次输入的新密码不一致";
    pwdInvalidField.value = "confirm";
    confirmPwdInput.value?.focus();
    return;
  }

  pwdSaving.value = true;
  try {
    await api.put("/users/me/password", { old_password: oldPassword.value, new_password: newPassword.value });
    oldPassword.value = "";
    newPassword.value = "";
    confirmPassword.value = "";
    showPasswords.value = false;
    pwdMsg.value = "密码已更新，其他设备登录已失效";
  } catch (e: any) {
    pwdErr.value = typeof e?.detail?.detail === "string" ? e.detail.detail : (e?.message ?? "修改失败");
    pwdInvalidField.value = "old";
    oldPwdInput.value?.focus();
  } finally {
    pwdSaving.value = false;
  }
}
</script>

<template>
  <div class="settings-touch-target flex h-dvh w-full overflow-hidden bg-canvas text-fg">
    <!-- Hidden file input for avatar upload -->
    <input
      ref="avatarFileInput"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      class="visually-hidden"
      @change="onAvatarFileChange"
    />

    <!-- Desktop Fixed Wide Sidebar (hidden on independent password sub-page) -->
    <aside
      v-if="activePage !== 'password'"
      aria-label="设置导航"
      class="hidden w-[300px] shrink-0 flex-col bg-sidebar p-4 md:flex lg:w-[320px]"
    >
      <!-- Top Back to Chat button -->
      <div class="mb-3 flex items-center justify-between">
        <button
          type="button"
          class="focus-ring inline-flex h-9 items-center gap-1.5 rounded-xl px-2.5 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-hover/80 hover:text-fg"
          @click="goBackToChat"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
          </svg>
          <span>返回对话</span>
        </button>
      </div>

      <!-- Theme Switcher in sidebar -->
      <fieldset class="m-0 mb-5 border-0 p-0">
        <legend class="visually-hidden">外观主题</legend>
        <div class="grid grid-cols-3 gap-1 rounded-xl bg-surface p-1 dark:bg-canvas">
          <label
            v-for="opt in themeOptions"
            :key="opt.value"
            class="theme-segment-option flex h-8.5 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-2 text-[12.5px] transition-all has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-accent"
            :class="
              preference === opt.value
                ? 'bg-canvas font-medium text-fg shadow-xs dark:bg-active'
                : 'text-fg-muted hover:text-fg'
            "
          >
            <input
              type="radio"
              name="desktop_theme_preference"
              class="visually-hidden"
              :value="opt.value"
              :checked="preference === opt.value"
              @change="setTheme(opt.value)"
            />
            <svg
              v-if="opt.value === 'system'"
              class="h-3.5 w-3.5 shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
              aria-hidden="true"
            >
              <rect x="3" y="4" width="18" height="12" rx="2" />
              <path stroke-linecap="round" d="M8 20h8M12 16v4" />
            </svg>
            <svg
              v-else-if="opt.value === 'light'"
              class="h-3.5 w-3.5 shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="4" />
              <path stroke-linecap="round" d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
            </svg>
            <svg
              v-else
              class="h-3.5 w-3.5 shrink-0"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.85"
              aria-hidden="true"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
            </svg>
            <span>{{ opt.label }}</span>
          </label>
        </div>
      </fieldset>

      <!-- User compact card -->
      <div class="mb-4 flex items-center gap-3 rounded-2xl bg-canvas/80 p-3 dark:bg-surface/70">
        <img
          v-if="auth.user?.avatar_url && !avatarLoadFailed"
          :src="auth.user.avatar_url"
          alt=""
          class="h-10 w-10 shrink-0 rounded-full bg-surface object-cover"
          @error="avatarLoadFailed = true"
        />
        <span
          v-else
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface text-[14px] font-semibold text-fg dark:bg-active"
          aria-hidden="true"
        >
          {{ initials }}
        </span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5">
            <span class="truncate text-[14px] font-semibold text-fg">{{ auth.user?.display_name || "用户" }}</span>
            <span class="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold leading-none" :class="tierBadgeClass">
              {{ credits.tierLabel }}
            </span>
          </div>
          <p class="mt-0.5 truncate text-[12px] text-fg-faint">{{ auth.user?.email }}</p>
        </div>
      </div>

      <!-- Main Section Tabs -->
      <nav class="flex-1 space-y-1.5">
        <button
          v-for="item in navItems"
          :key="item.key"
          type="button"
          class="focus-ring flex w-full items-center gap-3 rounded-2xl px-3.5 py-3 text-left transition-colors"
          :class="
            activePage === item.key
              ? 'bg-hover/90 text-fg dark:bg-active'
              : 'text-fg-muted hover:bg-hover/65 hover:text-fg'
          "
          @click="selectMainPage(item.key)"
        >
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-canvas/80 text-fg dark:bg-surface">
            <svg v-if="item.key === 'profile'" class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <circle cx="12" cy="8" r="4" />
              <path stroke-linecap="round" d="M4 20c0-3.5 3.6-6 8-6s8 2.5 8 6" />
            </svg>
            <svg v-else-if="item.key === 'membership'" class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l4 3 5-6 5 6 4-3-2 11H5L3 8z" />
            </svg>
            <svg v-else class="h-4.5 w-4.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.6l-1.7-4.6L6 9.3l4.3-1.7L12 3zM5 17l.9 2.1L8 20l-2.1.9L5 23l-.9-2.1L2 20l2.1-.9L5 17z" />
            </svg>
          </span>
          <span class="min-w-0 flex-1">
            <span class="block text-[14.5px] font-medium">{{ item.label }}</span>
            <span class="block truncate text-[12px] text-fg-faint">{{ item.desc }}</span>
          </span>
        </button>
      </nav>

      <!-- Sidebar Footer Actions (no top divider) -->
      <div class="mt-4 space-y-1.5 pt-2">
        <a
          v-if="auth.isAdmin && adminUrl"
          :href="adminUrl"
          class="focus-ring flex h-10 w-full items-center gap-2.5 rounded-xl px-3 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-hover/70 hover:text-fg"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 3l7 4v5c0 4.5-3 8.5-7 9-4-.5-7-4.5-7-9V7l7-4z" />
          </svg>
          <span>管理后台</span>
        </a>

        <button
          type="button"
          class="focus-ring flex h-10 w-full items-center gap-2.5 rounded-xl px-3 text-[13.5px] font-medium text-danger transition-colors hover:bg-danger-weak"
          @click="logoutModalOpen = true"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
          <span>退出登录</span>
        </button>
      </div>
    </aside>

    <!-- Mobile Level 1: Settings Root Menu (No sidebar on mobile) -->
    <div
      v-if="showMobileMenu"
      v-scrollbar
      class="custom-scrollbar flex flex-1 flex-col overflow-y-auto bg-canvas [scrollbar-gutter:auto] md:hidden"
    >
      <header class="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2.5 bg-canvas/90 px-3.5 backdrop-blur-md">
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          aria-label="返回对话"
          @click="goBackToChat"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <h1 class="text-[16px] font-semibold text-fg">设置</h1>
      </header>

      <div class="flex flex-1 flex-col gap-4 px-4 pb-6 pt-2">
        <!-- First row: 3-way Theme Switcher -->
        <fieldset class="m-0 border-0 p-0">
          <legend class="visually-hidden">外观主题</legend>
          <div class="grid grid-cols-3 gap-1 rounded-2xl bg-surface p-1">
            <label
              v-for="opt in themeOptions"
              :key="opt.value"
              class="theme-segment-option flex h-10 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-xl px-2 text-[13px] transition-all has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-accent"
              :class="
                preference === opt.value
                  ? 'bg-canvas font-medium text-fg shadow-xs dark:bg-active'
                  : 'text-fg-muted hover:text-fg'
              "
            >
              <input
                type="radio"
                name="mobile_theme_preference"
                class="visually-hidden"
                :value="opt.value"
                :checked="preference === opt.value"
                @change="setTheme(opt.value)"
              />
              <span>{{ opt.label }}</span>
            </label>
          </div>
        </fieldset>

        <!-- Account brief -->
        <div class="flex items-center gap-3 rounded-2xl bg-sidebar p-3.5 dark:bg-surface">
          <img
            v-if="auth.user?.avatar_url && !avatarLoadFailed"
            :src="auth.user.avatar_url"
            alt=""
            class="h-12 w-12 shrink-0 rounded-full bg-surface object-cover"
            @error="avatarLoadFailed = true"
          />
          <span
            v-else
            class="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface text-[16px] font-semibold text-fg dark:bg-active"
            aria-hidden="true"
          >
            {{ initials }}
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5">
              <span class="truncate text-[15px] font-semibold text-fg">{{ auth.user?.display_name || "用户" }}</span>
              <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-none" :class="tierBadgeClass">
                {{ credits.tierLabel }}
              </span>
            </div>
            <p class="mt-0.5 truncate text-[12.5px] text-fg-faint">{{ auth.user?.email }}</p>
          </div>
        </div>

        <!-- Level 1 menu entries -->
        <nav aria-label="设置分类" class="space-y-2">
          <button
            v-for="item in navItems"
            :key="item.key"
            type="button"
            class="focus-ring flex w-full items-center gap-3 rounded-2xl bg-sidebar px-4 py-3.5 text-left transition-colors active:bg-hover dark:bg-surface"
            @click="selectMainPage(item.key)"
          >
            <span class="min-w-0 flex-1">
              <span class="block text-[15px] font-medium text-fg">{{ item.label }}</span>
              <span class="mt-0.5 block truncate text-[12.5px] text-fg-faint">{{ item.desc }}</span>
            </span>
            <svg class="h-4.5 w-4.5 shrink-0 text-fg-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
            </svg>
          </button>
        </nav>

        <div class="mt-auto space-y-2 pt-3">
          <a
            v-if="auth.isAdmin && adminUrl"
            :href="adminUrl"
            class="focus-ring flex h-11 w-full items-center justify-center rounded-2xl bg-sidebar text-[14px] font-medium text-fg-muted transition-colors hover:bg-hover dark:bg-surface"
          >
            管理后台
          </a>
          <button
            type="button"
            class="focus-ring flex h-11 w-full items-center justify-center rounded-2xl bg-danger-weak text-[14px] font-medium text-danger transition-opacity hover:opacity-90"
            @click="logoutModalOpen = true"
          >
            退出登录
          </button>
        </div>
      </div>
    </div>

    <!-- Main Content Area (Desktop right pane OR Mobile Level 2 sub-page) -->
    <main
      v-else
      class="flex min-w-0 flex-1 flex-col overflow-hidden bg-canvas"
    >
      <!-- Mobile Level 2 Sticky Header with Back Button -->
      <header class="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2.5 bg-canvas/90 px-3.5 backdrop-blur-md md:hidden">
        <button
          type="button"
          class="focus-ring flex h-10 w-10 items-center justify-center rounded-xl text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          :aria-label="activePage === 'password' ? '返回用户信息' : '返回设置'"
          @click="goBackFromMobilePage"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <h1 class="truncate text-[16px] font-semibold text-fg">{{ pageTitle }}</h1>
      </header>

      <div v-scrollbar class="custom-scrollbar flex-1 overflow-y-auto px-4 pb-8 pt-3 [scrollbar-gutter:auto] md:px-8 md:py-7 lg:px-10">
        <!-- Page 1: Profile -->
        <div v-if="activePage === 'profile'" class="w-full space-y-5">
          <div class="hidden md:block">
            <h1 class="text-[20px] font-semibold tracking-tight text-fg">用户信息</h1>
            <p class="mt-1 text-[13.5px] text-fg-muted">点击头像更换照片，完善你的个人资料与账号安全设置。</p>
          </div>

          <!-- Avatar & Identity Card (click avatar to upload) -->
          <section class="flex flex-col gap-4 rounded-[24px] bg-sidebar p-5 sm:flex-row sm:items-center dark:bg-surface">
            <div class="flex items-center gap-4">
              <button
                type="button"
                class="focus-ring group relative h-16 w-16 shrink-0 overflow-hidden rounded-full ring-1 ring-line transition-transform active:scale-95"
                aria-label="点击上传或更换头像"
                title="点击更换头像"
                @click="triggerAvatarPick"
              >
                <img
                  v-if="auth.user?.avatar_url && !avatarLoadFailed"
                  :src="auth.user.avatar_url"
                  alt=""
                  class="h-full w-full bg-surface object-cover"
                  @error="avatarLoadFailed = true"
                />
                <span
                  v-else
                  class="flex h-full w-full items-center justify-center bg-surface text-[20px] font-semibold text-fg dark:bg-active"
                  aria-hidden="true"
                >
                  {{ initials }}
                </span>
                <span
                  class="absolute inset-0 flex items-center justify-center bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
                  aria-hidden="true"
                >
                  <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" />
                    <circle cx="12" cy="13" r="4" />
                  </svg>
                </span>
              </button>

              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="truncate text-[15.5px] font-semibold text-fg">{{ auth.user?.display_name }}</span>
                  <BaseBadge v-if="auth.user?.email_verified_at" tone="green">已验证</BaseBadge>
                  <BaseBadge v-if="auth.isAdmin" tone="brand">管理员</BaseBadge>
                </div>
                <p class="mt-0.5 truncate text-[13px] text-fg-muted">{{ auth.user?.email }}</p>
                <p class="mt-0.5 text-[12px] text-fg-faint">注册于 {{ joinedAt }}</p>
              </div>
            </div>

            <div class="flex flex-wrap items-center gap-2 sm:ml-auto">
              <BaseButton
                v-if="auth.user?.avatar_url"
                variant="ghost"
                size="sm"
                rounded="full"
                :loading="avatarDeleting"
                @click="removeAvatar"
              >
                移除头像
              </BaseButton>
              <span v-if="avatarFeedback" role="status" class="text-[12px] text-fg-muted">
                {{ avatarFeedback }}
              </span>
            </div>
          </section>

          <!-- Extended Profile Form -->
          <form
            method="POST"
            action="/api/users/me"
            aria-label="个人资料"
            class="rounded-[24px] bg-sidebar p-5 dark:bg-surface"
            @submit.prevent="saveProfile"
          >
            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <div class="min-w-0">
                <label for="settings-display-name" class="mb-1.5 block text-[13px] font-medium text-fg-muted">
                  用户名（可用于登录，全局唯一）
                </label>
                <input
                  id="settings-display-name"
                  ref="displayNameInput"
                  v-model="displayName"
                  name="display_name"
                  type="text"
                  maxlength="80"
                  autocomplete="username"
                  autocorrect="off"
                  autocapitalize="none"
                  :spellcheck="false"
                  enterkeyhint="next"
                  placeholder="设置唯一用户名"
                  :aria-invalid="profileInvalidField === 'displayName' ? 'true' : undefined"
                  class="focus-ring h-10 w-full rounded-xl border bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  :class="profileInvalidField === 'displayName' ? 'border-danger' : 'border-line/80'"
                  @input="onProfileInput"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-gender" class="mb-1.5 block text-[13px] font-medium text-fg-muted">性别</label>
                <div class="flex gap-2">
                  <select
                    id="settings-gender"
                    v-model="genderSelect"
                    name="gender"
                    class="focus-ring h-10 min-w-0 flex-1 rounded-xl border border-line/80 bg-canvas px-3 text-[14px] text-fg transition-colors hover:border-line-strong"
                    @change="onProfileInput"
                  >
                    <option value="">未设置</option>
                    <option value="男">男</option>
                    <option value="女">女</option>
                    <option value="保密">保密</option>
                    <option value="__custom__">自定义…</option>
                  </select>
                  <input
                    v-if="genderSelect === '__custom__'"
                    v-model="customGender"
                    type="text"
                    maxlength="40"
                    aria-label="自定义性别"
                    placeholder="输入自定义性别"
                    class="focus-ring h-10 min-w-0 flex-1 rounded-xl border border-line/80 bg-canvas px-3 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                    @input="onProfileInput"
                  />
                </div>
              </div>

              <div class="min-w-0">
                <label for="settings-birthday" class="mb-1.5 block text-[13px] font-medium text-fg-muted">生日</label>
                <input
                  id="settings-birthday"
                  v-model="birthday"
                  name="birthday"
                  type="date"
                  autocomplete="bday"
                  class="focus-ring h-10 w-full rounded-xl border border-line/80 bg-canvas px-3.5 text-[14px] text-fg transition-colors hover:border-line-strong"
                  @input="onProfileInput"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-occupation" class="mb-1.5 block text-[13px] font-medium text-fg-muted">
                  职业 / 头衔
                </label>
                <input
                  id="settings-occupation"
                  v-model="occupation"
                  name="occupation"
                  type="text"
                  maxlength="80"
                  autocomplete="organization-title"
                  enterkeyhint="next"
                  placeholder="例如：产品经理 / 工程师"
                  class="focus-ring h-10 w-full rounded-xl border border-line/80 bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  @input="onProfileInput"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-location" class="mb-1.5 block text-[13px] font-medium text-fg-muted">所在地区</label>
                <input
                  id="settings-location"
                  v-model="location"
                  name="location"
                  type="text"
                  maxlength="80"
                  autocomplete="address-level2"
                  enterkeyhint="next"
                  placeholder="例如：上海 / 北京"
                  class="focus-ring h-10 w-full rounded-xl border border-line/80 bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  @input="onProfileInput"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-phone" class="mb-1.5 block text-[13px] font-medium text-fg-muted">联系电话</label>
                <input
                  id="settings-phone"
                  ref="phoneInput"
                  v-model="phone"
                  name="phone"
                  type="tel"
                  maxlength="32"
                  autocomplete="tel"
                  inputmode="tel"
                  enterkeyhint="next"
                  placeholder="+86 138 0000 0000"
                  :aria-invalid="profileInvalidField === 'phone' ? 'true' : undefined"
                  class="focus-ring h-10 w-full rounded-xl border bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  :class="profileInvalidField === 'phone' ? 'border-danger' : 'border-line/80'"
                  @input="onProfileInput"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-website" class="mb-1.5 block text-[13px] font-medium text-fg-muted">个人主页</label>
                <input
                  id="settings-website"
                  ref="websiteInput"
                  v-model="website"
                  name="website"
                  type="url"
                  maxlength="255"
                  autocomplete="url"
                  autocorrect="off"
                  autocapitalize="none"
                  :spellcheck="false"
                  enterkeyhint="next"
                  placeholder="https://example.com"
                  :aria-invalid="profileInvalidField === 'website' ? 'true' : undefined"
                  class="focus-ring h-10 w-full rounded-xl border bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  :class="profileInvalidField === 'website' ? 'border-danger' : 'border-line/80'"
                  @input="onProfileInput"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-language" class="mb-1.5 block text-[13px] font-medium text-fg-muted">偏好语言</label>
                <select
                  id="settings-language"
                  v-model="preferredLanguage"
                  name="preferred_language"
                  class="focus-ring h-10 w-full rounded-xl border border-line/80 bg-canvas px-3 text-[14px] text-fg transition-colors hover:border-line-strong"
                  @change="onProfileInput"
                >
                  <option v-for="lang in languageOptions" :key="lang.value" :value="lang.value">{{ lang.label }}</option>
                </select>
              </div>

              <div class="min-w-0">
                <label for="settings-timezone" class="mb-1.5 block text-[13px] font-medium text-fg-muted">时区</label>
                <select
                  id="settings-timezone"
                  v-model="timezone"
                  name="timezone"
                  class="focus-ring h-10 w-full rounded-xl border border-line/80 bg-canvas px-3 text-[14px] text-fg transition-colors hover:border-line-strong"
                  @change="onProfileInput"
                >
                  <option v-for="tz in timezoneOptions" :key="tz.value" :value="tz.value">{{ tz.label }}</option>
                </select>
              </div>

              <div class="col-span-full min-w-0">
                <div class="mb-1.5 flex items-center justify-between gap-2">
                  <label for="settings-bio" class="text-[13px] font-medium text-fg-muted">个人简介</label>
                  <span class="text-[12px] tabular-nums text-fg-faint">{{ bio.length }} / 300</span>
                </div>
                <textarea
                  id="settings-bio"
                  v-model="bio"
                  name="bio"
                  rows="3"
                  maxlength="300"
                  placeholder="介绍一下你自己、专业背景或常用工作流…"
                  class="focus-ring w-full resize-y rounded-xl border border-line/80 bg-canvas px-3.5 py-2.5 text-[14px] leading-relaxed text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  @input="onProfileInput"
                />
              </div>
            </div>

            <div class="mt-4 flex items-center justify-between gap-3">
              <div class="min-w-0 flex-1">
                <p v-if="profileErr" role="alert" class="text-[13px] text-danger">{{ profileErr }}</p>
                <p v-else-if="profileMsg" role="status" aria-live="polite" class="text-[13px] text-success">
                  {{ profileMsg }}
                </p>
              </div>
              <BaseButton type="submit" rounded="full" :loading="profileSaving" class="shrink-0">保存资料</BaseButton>
            </div>
          </form>

          <!-- Security entry -> independent Password sub-page -->
          <section class="flex items-center justify-between gap-4 rounded-[24px] bg-sidebar p-5 dark:bg-surface">
            <div class="min-w-0">
              <h2 class="text-[15px] font-semibold text-fg">账号安全 · 修改密码</h2>
              <p class="mt-0.5 text-[13px] text-fg-muted">定期更新密码以保障账号安全，修改后其他设备将自动下线。</p>
            </div>
            <BaseButton variant="secondary" rounded="full" class="shrink-0" @click="openPasswordPage">
              <span>修改密码</span>
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6" />
              </svg>
            </BaseButton>
          </section>
        </div>

        <!-- Sub-page under Profile: Password (with Back Button) -->
        <div v-else-if="activePage === 'password'" class="w-full space-y-5">
          <div class="hidden items-center gap-3 md:flex">
            <button
              type="button"
              class="focus-ring inline-flex h-9 items-center gap-1.5 rounded-full bg-sidebar px-3.5 text-[13.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg dark:bg-surface"
              @click="activePage = 'profile'"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6" />
              </svg>
              <span>返回用户信息</span>
            </button>
            <h1 class="text-[20px] font-semibold tracking-tight text-fg">修改密码</h1>
          </div>

          <form
            method="POST"
            action="/api/users/me/password"
            aria-label="修改密码"
            class="rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface"
            @submit.prevent="savePassword"
          >
            <input
              type="email"
              name="username"
              :value="auth.user?.email ?? ''"
              autocomplete="username"
              tabindex="-1"
              aria-hidden="true"
              class="visually-hidden"
            />

            <div class="mb-4 flex items-center justify-between gap-2">
              <p class="text-[13.5px] text-fg-muted">修改密码后，其他已登录设备的会话将立即失效。</p>
              <button
                type="button"
                class="focus-ring inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                :aria-pressed="showPasswords"
                @click="showPasswords = !showPasswords"
              >
                <span>{{ showPasswords ? "隐藏密码" : "显示密码" }}</span>
              </button>
            </div>

            <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div class="min-w-0">
                <label for="settings-old-password" class="mb-1.5 block text-[13px] font-medium text-fg-muted">
                  当前密码
                </label>
                <input
                  id="settings-old-password"
                  ref="oldPwdInput"
                  v-model="oldPassword"
                  name="old_password"
                  :type="showPasswords ? 'text' : 'password'"
                  autocomplete="current-password"
                  enterkeyhint="next"
                  placeholder="输入当前密码"
                  :aria-invalid="pwdInvalidField === 'old' ? 'true' : undefined"
                  class="focus-ring h-10 w-full rounded-xl border bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  :class="pwdInvalidField === 'old' ? 'border-danger' : 'border-line/80'"
                  @input="clearPasswordError"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-new-password" class="mb-1.5 block text-[13px] font-medium text-fg-muted">
                  新密码（至少 8 位）
                </label>
                <input
                  id="settings-new-password"
                  ref="newPwdInput"
                  v-model="newPassword"
                  name="new_password"
                  :type="showPasswords ? 'text' : 'password'"
                  minlength="8"
                  maxlength="128"
                  autocomplete="new-password"
                  enterkeyhint="next"
                  placeholder="设置新密码"
                  :aria-invalid="pwdInvalidField === 'new' ? 'true' : undefined"
                  class="focus-ring h-10 w-full rounded-xl border bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  :class="pwdInvalidField === 'new' ? 'border-danger' : 'border-line/80'"
                  @input="clearPasswordError"
                  @blur="validateNewPasswordBlur"
                />
              </div>

              <div class="min-w-0">
                <label for="settings-confirm-password" class="mb-1.5 block text-[13px] font-medium text-fg-muted">
                  确认新密码
                </label>
                <input
                  id="settings-confirm-password"
                  ref="confirmPwdInput"
                  v-model="confirmPassword"
                  name="confirm_password"
                  :type="showPasswords ? 'text' : 'password'"
                  minlength="8"
                  maxlength="128"
                  autocomplete="new-password"
                  enterkeyhint="done"
                  placeholder="再次输入新密码"
                  :aria-invalid="pwdInvalidField === 'confirm' ? 'true' : undefined"
                  class="focus-ring h-10 w-full rounded-xl border bg-canvas px-3.5 text-[14px] text-fg transition-colors placeholder:text-fg-faint hover:border-line-strong"
                  :class="pwdInvalidField === 'confirm' ? 'border-danger' : 'border-line/80'"
                  @input="clearPasswordError"
                  @blur="validateConfirmPasswordBlur"
                />
              </div>
            </div>

            <div class="mt-5 flex items-center justify-between gap-3">
              <div class="min-w-0 flex-1">
                <p v-if="pwdErr" role="alert" class="text-[13px] text-danger">{{ pwdErr }}</p>
                <p v-else-if="pwdMsg" role="status" aria-live="polite" class="text-[13px] text-success">{{ pwdMsg }}</p>
              </div>
              <BaseButton type="submit" rounded="full" :loading="pwdSaving" class="shrink-0">更新密码</BaseButton>
            </div>
          </form>
        </div>

        <!-- Page 2: Membership -->
        <div v-else-if="activePage === 'membership'" class="w-full space-y-5">
          <div class="hidden md:block">
            <h1 class="text-[20px] font-semibold tracking-tight text-fg">会员与额度</h1>
            <p class="mt-1 text-[13.5px] text-fg-muted">查看当前会员档位、滚动额度剩余与兑换邀请码。</p>
          </div>
          <div class="rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
            <MembershipPanel />
          </div>
        </div>

        <!-- Page 3: Persona -->
        <div v-else-if="activePage === 'persona'" class="w-full space-y-5">
          <div class="hidden md:block">
            <h1 class="text-[20px] font-semibold tracking-tight text-fg">助理人设</h1>
            <p class="mt-1 text-[13.5px] text-fg-muted">定制你的个人 AI 助理语气、专业角色与回答规范。</p>
          </div>
          <div class="rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
            <PersonaEditor :persona="auth.user?.persona ?? ''" />
          </div>
        </div>
      </div>
    </main>

    <!-- Avatar Cropper Modal -->
    <AvatarCropModal
      :open="cropModalOpen"
      :file="pendingAvatarFile"
      @close="cropModalOpen = false"
      @uploaded="onAvatarUploaded"
    />

    <!-- Logout Confirmation Modal -->
    <BaseModal :open="logoutModalOpen" title="退出登录" @close="logoutModalOpen = false">
      <p class="text-[14.5px] leading-relaxed text-fg-muted">
        确定要退出当前账号吗？退出后需要重新登录才能继续使用。
      </p>
      <template #footer>
        <BaseButton variant="soft" rounded="full" :disabled="loggingOut" @click="logoutModalOpen = false">
          取消
        </BaseButton>
        <BaseButton variant="danger" rounded="full" :loading="loggingOut" @click="confirmLogout">
          确认退出
        </BaseButton>
      </template>
    </BaseModal>
  </div>
</template>
