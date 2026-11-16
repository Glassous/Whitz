<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import AuthLayout from "../components/AuthLayout.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

const email = ref("");
const password = ref("");
const showPassword = ref(false);
const error = ref<string | null>(null);
const loading = ref(false);

watch([email, password], () => {
  if (error.value) error.value = null;
});

async function submit() {
  error.value = null;
  if (!email.value.trim() || !password.value) {
    error.value = "请输入邮箱和密码";
    return;
  }
  loading.value = true;
  try {
    await auth.login(email.value.trim(), password.value);
    const rawRedirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    const redirect = rawRedirect.startsWith("/") && !rawRedirect.startsWith("//") ? rawRedirect : "/";
    await router.push(redirect);
  } catch (e: any) {
    error.value = e?.detail?.detail ?? e?.message ?? "登录失败";
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

    <form class="space-y-3.5" @submit.prevent="submit">
      <BaseInput
        v-model="email"
        label="邮箱"
        type="email"
        placeholder="you@example.com"
        autocomplete="email"
        autofocus
      />

      <BaseInput
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
