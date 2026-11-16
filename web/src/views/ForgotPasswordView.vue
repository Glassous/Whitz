<script setup lang="ts">
import { ref } from "vue";
import AuthLayout from "../components/AuthLayout.vue";
import BaseInput from "../components/ui/BaseInput.vue";
import BaseButton from "../components/ui/BaseButton.vue";
import FormError from "../components/ui/FormError.vue";
import { api } from "../api/client";
import type { SecurityQuestion } from "../types";

const step = ref<1 | 2 | 3>(1);
const email = ref("");
const questions = ref<SecurityQuestion[]>([]);
const answers = ref<string[]>(["", ""]);
const newPassword = ref("");
const confirm = ref("");
const error = ref<string | null>(null);
const loading = ref(false);

async function loadQuestions() {
  error.value = null;
  if (!email.value.trim()) {
    error.value = "请输入注册邮箱";
    return;
  }
  loading.value = true;
  try {
    questions.value = await api.get<SecurityQuestion[]>(
      `/auth/security-questions?email=${encodeURIComponent(email.value.trim())}`,
    );
    answers.value = questions.value.map(() => "");
    step.value = 2;
  } catch (e: any) {
    error.value = e?.detail?.detail ?? "该邮箱未注册或请求过于频繁";
  } finally {
    loading.value = false;
  }
}

async function resetPassword() {
  error.value = null;
  if (answers.value.some((a) => !a.trim())) {
    error.value = "请完整回答密保问题";
    return;
  }
  if (newPassword.value.length < 8) {
    error.value = "新密码至少 8 位";
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
      answers: answers.value,
      new_password: newPassword.value,
    });
    step.value = 3;
  } catch (e: any) {
    error.value = e?.detail?.detail ?? "重置失败，请检查密保答案";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout title="找回密码" subtitle="通过注册时设置的密保问题重置密码">
    <form v-if="step === 1" class="space-y-3.5" @submit.prevent="loadQuestions">
      <BaseInput v-model="email" label="注册邮箱" type="email" placeholder="you@example.com" autofocus />
      <FormError :message="error" />
      <BaseButton type="submit" size="lg" block :loading="loading">下一步</BaseButton>
    </form>

    <form v-else-if="step === 2" class="space-y-2.5" @submit.prevent="resetPassword">
      <div v-for="(q, i) in questions" :key="q.position" class="rounded-xl border border-line bg-surface/40 p-3">
        <p class="mb-1.5 text-[12.5px] font-medium text-fg">{{ q.question }}</p>
        <BaseInput v-model="answers[i]" size="sm" placeholder="请输入密保答案" />
      </div>
      <div class="grid gap-2.5 sm:grid-cols-2">
        <BaseInput v-model="newPassword" size="sm" label="新密码" type="password" placeholder="至少 8 位" />
        <BaseInput v-model="confirm" size="sm" label="确认新密码" type="password" placeholder="再次输入" />
      </div>
      <FormError :message="error" />
      <div class="flex items-center gap-2.5 pt-1">
        <BaseButton variant="secondary" size="lg" :disabled="loading" @click="step = 1">上一步</BaseButton>
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
