<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import ThemeToggle from "../components/ui/ThemeToggle.vue";
import { readableError } from "../api/client";
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
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/";
    await router.push(redirect);
  } catch (e: unknown) {
    error.value = readableError(e);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="relative flex min-h-dvh flex-col bg-canvas">
    <div class="flex items-center justify-end px-5 py-4 sm:px-8">
      <ThemeToggle />
    </div>

    <div class="flex flex-1 items-center justify-center px-5 pb-16">
      <div class="animate-rise w-full max-w-[380px]">
        <div class="mb-8 flex items-center gap-3">
          <div class="flex h-11 w-11 items-center justify-center rounded-[13px] bg-primary text-primary-fg">
            <span class="text-[15px] font-semibold tracking-tight">W</span>
          </div>
          <div>
            <p class="text-[15px] font-semibold leading-tight tracking-tight text-fg">Whitz 管理后台</p>
            <p class="mt-0.5 text-[12px] text-fg-faint">用户与审计管理</p>
          </div>
        </div>

        <div class="rounded-2xl border border-line bg-canvas p-5 sm:p-6">
          <div class="mb-5 flex items-start gap-2.5 rounded-xl bg-surface px-3 py-2.5">
            <svg class="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z" />
            </svg>
            <p class="text-[12px] leading-relaxed text-fg-muted">仅管理员账号可登录，普通用户会被立即退出。</p>
          </div>

          <form class="space-y-4" @submit.prevent="submit">
            <BaseInput
              v-model="email"
              label="管理员邮箱"
              type="email"
              placeholder="admin@example.com"
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
                  <svg
                    v-else
                    class="h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.75"
                  >
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

            <BaseButton type="submit" size="lg" block :loading="loading">登录</BaseButton>
          </form>
        </div>

        <p class="mt-6 text-center text-[11px] text-fg-faint">© 2026 Whitz · 管理员入口</p>
      </div>
    </div>
  </div>
</template>
