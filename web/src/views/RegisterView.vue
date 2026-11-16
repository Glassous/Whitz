<script setup lang="ts">
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import AuthLayout from "../components/AuthLayout.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import SecurityQuestionsForm from "../components/settings/SecurityQuestionsForm.vue";
import { useAuthStore } from "../stores/auth";
import type { SecurityQuestionInput } from "../types";

const auth = useAuthStore();
const router = useRouter();

const step = ref<1 | 2>(1);
const displayName = ref("");
const email = ref("");
const password = ref("");
const confirm = ref("");
const showPassword = ref(false);
const showConfirm = ref(false);
const questions = ref<SecurityQuestionInput[]>([]);
const error = ref<string | null>(null);
const loading = ref(false);

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

watch([displayName, email, password, confirm, questions], () => {
  if (error.value) error.value = null;
}, { deep: true });

function validateStep1(): string | null {
  if (!displayName.value.trim()) return "请输入昵称";
  if (displayName.value.trim().length > 80) return "昵称不能超过 80 个字符";
  const trimmedEmail = email.value.trim();
  if (!trimmedEmail || !EMAIL_RE.test(trimmedEmail)) return "请输入有效的邮箱地址";
  if (password.value.length < 8) return "密码至少需要 8 位";
  if (password.value.length > 128) return "密码不能超过 128 位";
  if (password.value !== confirm.value) return "两次输入的密码不一致";
  return null;
}

function nextStep() {
  const err = validateStep1();
  if (err) {
    error.value = err;
    return;
  }
  error.value = null;
  step.value = 2;
}

function prevStep() {
  if (loading.value) return;
  error.value = null;
  step.value = 1;
}

async function submit() {
  error.value = null;
  const step1Err = validateStep1();
  if (step1Err) {
    step.value = 1;
    error.value = step1Err;
    return;
  }
  const qs = questions.value;
  if (qs.length !== 2 || qs.some((q) => q.question.trim().length < 2 || !q.answer.trim())) {
    error.value = "请完整设置两个密保问题与答案";
    return;
  }
  if (qs[0].question === qs[1].question) {
    error.value = "两个密保问题不能相同";
    return;
  }
  loading.value = true;
  try {
    await auth.register({
      email: email.value.trim(),
      password: password.value,
      display_name: displayName.value.trim(),
      security_questions: qs,
    });
    await router.push("/");
  } catch (e: any) {
    const detail = e?.detail?.detail ?? e?.message ?? "注册失败";
    error.value = typeof detail === "string" ? detail : "注册失败，请检查输入信息";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout
    mode="register"
    :title="step === 1 ? '创建账号' : '设置密保问题'"
    :subtitle="step === 1 ? '第一步：填写基础账号与登录密码' : '第二步：用于忘记密码时安全找回账号'"
  >
    <!-- Compact 2-step indicator -->
    <div class="mb-4 flex items-center gap-2">
      <button
        type="button"
        class="focus-ring flex flex-1 items-center gap-2 rounded-xl border px-2.5 py-2 text-left transition-colors"
        :class="
          step === 1
            ? 'border-accent/40 bg-accent-weak/60 text-fg'
            : 'border-line bg-surface/60 text-fg-muted hover:border-line-strong hover:text-fg'
        "
        @click="prevStep"
      >
        <span
          class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
          :class="
            step === 1
              ? 'bg-accent text-accent-fg'
              : 'bg-success-weak text-success'
          "
        >
          <svg v-if="step === 2" class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          <template v-else>1</template>
        </span>
        <span class="truncate text-[12px] font-medium">账号与密码</span>
      </button>

      <div class="h-px w-3 shrink-0 bg-line-strong" />

      <div
        class="flex flex-1 items-center gap-2 rounded-xl border px-2.5 py-2 transition-colors"
        :class="
          step === 2
            ? 'border-accent/40 bg-accent-weak/60 text-fg'
            : 'border-line bg-canvas text-fg-faint'
        "
      >
        <span
          class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
          :class="step === 2 ? 'bg-accent text-accent-fg' : 'bg-surface text-fg-faint'"
        >
          2
        </span>
        <span class="truncate text-[12px] font-medium">密保问题</span>
      </div>
    </div>

    <!-- Step 1: Account & Password -->
    <form v-show="step === 1" class="space-y-3" @submit.prevent="nextStep">
      <div class="grid gap-3 sm:grid-cols-2">
        <BaseInput v-model="displayName" size="sm" label="昵称" placeholder="怎么称呼你？" autofocus />
        <BaseInput
          v-model="email"
          size="sm"
          label="邮箱"
          type="email"
          placeholder="you@example.com"
          autocomplete="email"
        />
      </div>

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

      <FormError :message="step === 1 ? error : null" />

      <div class="pt-1">
        <BaseButton type="submit" size="lg" block>
          下一步：设置密保
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </BaseButton>
      </div>
    </form>

    <!-- Step 2: Security Questions -->
    <form v-show="step === 2" class="space-y-3" @submit.prevent="submit">
      <div class="flex items-center justify-between rounded-xl bg-surface px-3 py-2 text-[12px]">
        <span class="truncate text-fg-muted">
          注册账号：<span class="font-medium text-fg">{{ email.trim() }}</span>
        </span>
        <button
          type="button"
          class="focus-ring shrink-0 rounded px-1.5 py-0.5 font-medium text-accent transition-opacity hover:opacity-75"
          :disabled="loading"
          @click="prevStep"
        >
          修改
        </button>
      </div>

      <SecurityQuestionsForm v-model="questions" compact />

      <FormError :message="step === 2 ? error : null" />

      <div class="flex items-center gap-2.5 pt-1">
        <BaseButton variant="secondary" size="lg" :disabled="loading" @click="prevStep">上一步</BaseButton>
        <BaseButton type="submit" size="lg" class="flex-1" :loading="loading">完成注册</BaseButton>
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
