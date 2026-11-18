<script setup lang="ts">
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import AuthLayout from "../components/AuthLayout.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import { extractErrorMessage, isValidEmail, useEmailCode } from "../composables/useEmailCode";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();

const displayName = ref("");
const email = ref("");
const code = ref("");
const password = ref("");
const confirm = ref("");
const showPassword = ref(false);
const showConfirm = ref(false);
const error = ref<string | null>(null);
const loading = ref(false);

const { sending, cooldown, notice, sendCode } = useEmailCode("register");

watch([displayName, email, code, password, confirm], () => {
  if (error.value) error.value = null;
});

async function handleSendCode() {
  error.value = null;
  const res = await sendCode(email.value);
  if (!res.ok && res.error) {
    error.value = res.error;
  }
}

function validate(): string | null {
  const trimmedName = displayName.value.trim();
  if (!trimmedName) return "请输入用户名";
  if (trimmedName.length > 80) return "用户名不能超过 80 个字符";
  if (trimmedName.includes("@")) return "用户名不能包含 @ 符号";
  const trimmedEmail = email.value.trim();
  if (!trimmedEmail || !isValidEmail(trimmedEmail)) return "请输入有效的邮箱地址";
  if (!code.value.trim()) return "请输入邮箱验证码";
  if (password.value.length < 8) return "密码至少需要 8 位";
  if (password.value.length > 128) return "密码不能超过 128 位";
  if (password.value !== confirm.value) return "两次输入的密码不一致";
  return null;
}

async function submit() {
  error.value = null;
  const err = validate();
  if (err) {
    error.value = err;
    return;
  }
  loading.value = true;
  try {
    await auth.register({
      email: email.value.trim(),
      code: code.value.trim(),
      password: password.value,
      display_name: displayName.value.trim(),
    });
    await router.push("/");
  } catch (e: unknown) {
    error.value = extractErrorMessage(e, "注册失败，请检查输入信息");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout mode="register" title="创建账号" subtitle="通过邮箱验证码验证后即可开始对话">
    <form class="space-y-3" @submit.prevent="submit">
      <BaseInput
        v-model="displayName"
        name="display_name"
        size="sm"
        label="用户名"
        placeholder="设置唯一用户名，可用于登录"
        autocomplete="username"
        autocorrect="off"
        autocapitalize="none"
        :spellcheck="false"
        maxlength="80"
        enterkeyhint="next"
        required
        autofocus
      />

      <BaseInput
        v-model="email"
        size="sm"
        label="邮箱"
        type="email"
        placeholder="you@example.com"
        autocomplete="email"
      />

      <div class="space-y-1.5">
        <div class="flex items-end gap-2">
          <div class="min-w-0 flex-1">
            <BaseInput
              v-model="code"
              size="sm"
              label="邮箱验证码"
              placeholder="6 位数字验证码"
              autocomplete="one-time-code"
            />
          </div>
          <BaseButton
            type="button"
            variant="secondary"
            size="md"
            class="h-9.5 shrink-0"
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

      <div class="grid gap-3 sm:grid-cols-2">
        <BaseInput
          v-model="password"
          size="sm"
          label="密码"
          :type="showPassword ? 'text' : 'password'"
          placeholder="至少 8 位字符"
          autocomplete="new-password"
        >
          <template #suffix>
            <button
              type="button"
              class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              :aria-label="showPassword ? '隐藏密码' : '显示密码'"
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

        <BaseInput
          v-model="confirm"
          size="sm"
          label="确认密码"
          :type="showConfirm ? 'text' : 'password'"
          placeholder="再次输入密码"
          autocomplete="new-password"
        >
          <template #suffix>
            <button
              type="button"
              class="focus-ring flex h-7 w-7 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-fg"
              :aria-label="showConfirm ? '隐藏密码' : '显示密码'"
              @mousedown.prevent
              @click="showConfirm = !showConfirm"
            >
              <svg
                v-if="!showConfirm"
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
      </div>

      <FormError :message="error" />

      <div class="pt-1">
        <BaseButton type="submit" size="lg" block :loading="loading">完成注册</BaseButton>
      </div>
    </form>

    <template #footer>
      <p>
        已有账号？
        <router-link to="/login" class="font-medium text-accent hover:underline">去登录</router-link>
      </p>
    </template>
  </AuthLayout>
</template>
