<script setup lang="ts">
import { ref, watch } from "vue";
import AuthLayout from "../components/AuthLayout.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import { api } from "../api/client";
import { extractErrorMessage, isValidEmail, useEmailCode } from "../composables/useEmailCode";

const step = ref<1 | 2 | 3>(1);
const email = ref("");
const code = ref("");
const newPassword = ref("");
const confirm = ref("");
const error = ref<string | null>(null);
const loading = ref(false);

const { sending, cooldown, notice, sendCode, clearNotice } = useEmailCode("reset_password");

watch([email, code, newPassword, confirm], () => {
  if (error.value) error.value = null;
});

async function sendResetCode() {
  error.value = null;
  const trimmed = email.value.trim();
  if (!trimmed || !isValidEmail(trimmed)) {
    error.value = "请输入有效的注册邮箱";
    return;
  }
  const res = await sendCode(trimmed);
  if (res.ok) {
    step.value = 2;
  } else if (res.error) {
    error.value = res.error;
  }
}

async function resendResetCode() {
  error.value = null;
  const res = await sendCode(email.value);
  if (!res.ok && res.error) {
    error.value = res.error;
  }
}

function goBack() {
  error.value = null;
  clearNotice();
  step.value = 1;
}

async function resetPassword() {
  error.value = null;
  if (!code.value.trim()) {
    error.value = "请输入邮箱验证码";
    return;
  }
  if (newPassword.value.length < 8) {
    error.value = "新密码至少 8 位";
    return;
  }
  if (newPassword.value.length > 128) {
    error.value = "新密码不能超过 128 位";
    return;
  }
  if (newPassword.value !== confirm.value) {
    error.value = "两次输入的密码不一致";
    return;
  }
  loading.value = true;
  try {
    await api.post("/auth/reset-password", {
      email: email.value.trim(),
      code: code.value.trim(),
      new_password: newPassword.value,
    });
    step.value = 3;
  } catch (e: unknown) {
    error.value = extractErrorMessage(e, "重置失败，请检查验证码是否正确");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout title="找回密码" subtitle="通过注册邮箱接收验证码重置密码">
    <form v-if="step === 1" class="space-y-3.5" @submit.prevent="sendResetCode">
      <BaseInput v-model="email" label="注册邮箱" type="email" placeholder="you@example.com" autocomplete="email" autofocus />
      <FormError :message="error" />
      <BaseButton type="submit" size="lg" block :loading="sending" :disabled="cooldown > 0">
        {{ cooldown > 0 ? `请 ${cooldown}s 后重试` : "发送验证码" }}
      </BaseButton>
    </form>

    <form v-else-if="step === 2" class="space-y-3" @submit.prevent="resetPassword">
      <div class="flex items-center justify-between rounded-xl bg-surface px-3 py-2 text-[12px]">
        <span class="truncate text-fg-muted">
          验证邮箱：<span class="font-medium text-fg">{{ email.trim() }}</span>
        </span>
        <button
          type="button"
          class="focus-ring shrink-0 rounded px-1.5 py-0.5 font-medium text-accent transition-opacity hover:opacity-75"
          :disabled="loading"
          @click="goBack"
        >
          修改
        </button>
      </div>

      <div class="flex items-end gap-2">
        <div class="min-w-0 flex-1">
          <BaseInput
            v-model="code"
            size="sm"
            label="邮箱验证码"
            placeholder="6 位数字验证码"
            autocomplete="one-time-code"
            autofocus
          />
        </div>
        <BaseButton
          type="button"
          variant="secondary"
          size="md"
          class="h-9.5 shrink-0"
          :loading="sending"
          :disabled="cooldown > 0"
          @click="resendResetCode"
        >
          {{ cooldown > 0 ? `${cooldown}s 后重发` : "重新发送" }}
        </BaseButton>
      </div>

      <p v-if="notice" class="rounded-lg bg-success-weak/75 px-3 py-1.5 text-[12px] text-success">
        {{ notice }}
      </p>

      <div class="grid gap-2.5 sm:grid-cols-2">
        <BaseInput
          v-model="newPassword"
          size="sm"
          label="新密码"
          type="password"
          placeholder="至少 8 位"
          autocomplete="new-password"
        />
        <BaseInput
          v-model="confirm"
          size="sm"
          label="确认新密码"
          type="password"
          placeholder="再次输入"
          autocomplete="new-password"
        />
      </div>

      <FormError :message="error" />

      <div class="flex items-center gap-2.5 pt-1">
        <BaseButton variant="secondary" size="lg" :disabled="loading" @click="goBack">上一步</BaseButton>
        <BaseButton type="submit" size="lg" class="flex-1" :loading="loading">重置密码</BaseButton>
      </div>
    </form>

    <div v-else class="space-y-4 text-center">
      <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-success-weak text-success">
        <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>
      <p class="text-[13px] text-fg-muted">密码已重置，请使用新密码登录。</p>
      <BaseButton size="lg" block @click="$router.push('/login')">去登录</BaseButton>
    </div>

    <template #footer>
      <router-link to="/login" class="font-medium hover:text-fg">返回登录</router-link>
    </template>
  </AuthLayout>
</template>
