<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import AuthLayout from "../components/AuthLayout.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import { extractErrorMessage, isValidEmail, useEmailCode } from "../composables/useEmailCode";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

type LoginMode = "password" | "code";
const mode = ref<LoginMode>("password");
const account = ref("");
const password = ref("");
const code = ref("");
const showPassword = ref(false);
const error = ref<string | null>(null);
const loading = ref(false);

const { sending, cooldown, notice, sendCode, clearNotice } = useEmailCode("login");

watch([mode, account, password, code], () => {
  if (error.value) error.value = null;
});

watch(mode, () => {
  clearNotice();
});

async function handleSendCode() {
  error.value = null;
  const res = await sendCode(account.value);
  if (!res.ok && res.error) {
    error.value = res.error;
  }
}

async function submit() {
  error.value = null;
  const trimmedAccount = account.value.trim();
  if (!trimmedAccount) {
    error.value = mode.value === "password" ? "请输入邮箱或用户名" : "请输入有效的邮箱地址";
    return;
  }
  if (mode.value === "code" && !isValidEmail(trimmedAccount)) {
    error.value = "请输入有效的邮箱地址";
    return;
  }
  if (mode.value === "password" && !password.value) {
    error.value = "请输入登录密码";
    return;
  }
  if (mode.value === "code" && !code.value.trim()) {
    error.value = "请输入邮箱验证码";
    return;
  }
  loading.value = true;
  try {
    if (mode.value === "password") {
      await auth.login(trimmedAccount, password.value);
    } else {
      await auth.loginWithCode(trimmedAccount, code.value.trim());
    }
    const rawRedirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    const redirect = rawRedirect.startsWith("/") && !rawRedirect.startsWith("//") ? rawRedirect : "/";
    await router.push(redirect);
  } catch (e: unknown) {
    error.value = extractErrorMessage(e, "登录失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout mode="login" title="欢迎回来" subtitle="登录你的账号，继续上次的对话">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="auth.logoutNotice"
        role="status"
        class="mb-4 flex items-start gap-2.5 rounded-xl border px-3 py-2.5 text-[12.5px] leading-relaxed"
        :class="
          auth.logoutNotice.type === 'manual'
            ? 'border-success/25 bg-success-weak/80 text-success'
            : 'border-warning/30 bg-warning-weak text-warning'
        "
      >
        <svg
          v-if="auth.logoutNotice.type === 'manual'"
          class="mt-0.5 h-4 w-4 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <circle cx="12" cy="12" r="9" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.5 12.5l2.3 2.3 4.7-5" />
        </svg>
        <svg
          v-else
          class="mt-0.5 h-4 w-4 shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <circle cx="12" cy="12" r="9" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5V12l2.8 1.6" />
        </svg>
        <span class="flex-1 font-medium">{{ auth.logoutNotice.message }}</span>
        <button
          type="button"
          class="focus-ring -mr-0.5 rounded-md p-0.5 opacity-70 transition-opacity hover:opacity-100"
          aria-label="关闭提醒"
          @click="auth.clearLogoutNotice()"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
    </Transition>

    <div class="mb-4 flex items-center gap-4 border-b border-line text-[13px]">
      <button
        type="button"
        class="focus-ring relative pb-2 font-medium transition-colors"
        :class="mode === 'password' ? 'text-fg' : 'text-fg-muted hover:text-fg'"
        @click="mode = 'password'"
      >
        密码登录
        <span v-if="mode === 'password'" class="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" />
      </button>
      <button
        type="button"
        class="focus-ring relative pb-2 font-medium transition-colors"
        :class="mode === 'code' ? 'text-fg' : 'text-fg-muted hover:text-fg'"
        @click="mode = 'code'"
      >
        邮箱验证码登录
        <span v-if="mode === 'code'" class="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" />
      </button>
    </div>

    <form class="space-y-3.5" @submit.prevent="submit">
      <BaseInput
        v-model="account"
        :name="mode === 'password' ? 'identifier' : 'email'"
        :label="mode === 'password' ? '邮箱或用户名' : '邮箱'"
        :type="mode === 'password' ? 'text' : 'email'"
        :placeholder="mode === 'password' ? '邮箱地址或用户名' : 'you@example.com'"
        :autocomplete="mode === 'password' ? 'username' : 'email'"
        autocorrect="off"
        autocapitalize="none"
        :spellcheck="false"
        enterkeyhint="next"
        required
        autofocus
      />

      <BaseInput
        v-if="mode === 'password'"
        v-model="password"
        label="密码"
        :type="showPassword ? 'text' : 'password'"
        placeholder="请输入密码"
        autocomplete="current-password"
      >
        <template #label-action>
          <router-link
            to="/forgot"
            class="focus-ring rounded text-[12px] font-medium text-fg-muted transition-colors hover:text-fg"
          >
            忘记密码？
          </router-link>
        </template>
        <template #suffix>
          <button
            type="button"
            class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            :aria-pressed="showPassword"
            @mousedown.prevent
            @click="showPassword = !showPassword"
          >
            <svg
              v-if="!showPassword"
              class="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.75"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"
              />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path stroke-linecap="round" d="M3 3l18 18" />
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                d="M10.6 5.9A10.8 10.8 0 0112 5.8c6 0 9.5 6.2 9.5 6.2a17 17 0 01-3.2 3.9M6.5 7.4A17.3 17.3 0 002.5 12S6 18.2 12 18.2c1.6 0 3-.5 4.3-1.2"
              />
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.9 9.9a3 3 0 004.2 4.2" />
            </svg>
          </button>
        </template>
      </BaseInput>

      <div v-else class="space-y-2">
        <div class="flex items-end gap-2">
          <div class="min-w-0 flex-1">
            <BaseInput
              v-model="code"
              label="邮箱验证码"
              placeholder="6 位数字验证码"
              autocomplete="one-time-code"
            />
          </div>
          <BaseButton
            type="button"
            variant="secondary"
            size="lg"
            class="shrink-0"
            :loading="sending"
            :disabled="cooldown > 0"
            @click="handleSendCode"
          >
            {{ cooldown > 0 ? `${cooldown}s 后重发` : "发送验证码" }}
          </BaseButton>
        </div>
        <p v-if="notice" class="rounded-lg bg-success-weak/75 px-3 py-1.5 text-[12px] text-success">
          {{ notice }}
        </p>
      </div>

      <FormError :message="error" />

      <div class="pt-1">
        <BaseButton type="submit" size="lg" block :loading="loading">登录</BaseButton>
      </div>
    </form>

    <template #footer>
      <p>
        还没有账号？
        <router-link to="/register" class="font-medium text-accent hover:underline">免费注册</router-link>
      </p>
    </template>
  </AuthLayout>
</template>
