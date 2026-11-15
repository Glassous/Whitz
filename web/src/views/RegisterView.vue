<script setup lang="ts">
import { ref } from "vue";
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

const displayName = ref("");
const email = ref("");
const password = ref("");
const confirm = ref("");
const questions = ref<SecurityQuestionInput[]>([]);
const error = ref<string | null>(null);
const loading = ref(false);

async function submit() {
  error.value = null;
  if (password.value.length < 8) {
    error.value = "密码至少 8 位";
    return;
  }
  if (password.value !== confirm.value) {
    error.value = "两次输入的密码不一致";
    return;
  }
  const qs = questions.value;
  if (qs.length !== 2 || qs.some((q) => !q.question || !q.answer.trim())) {
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
    error.value = e?.detail?.detail ?? e?.message ?? "注册失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <AuthLayout title="创建账号" subtitle="只需几步，即可拥有你的个人 AI 助理。">
    <form class="space-y-4" @submit.prevent="submit">
      <BaseInput v-model="displayName" label="昵称" placeholder="怎么称呼你？" />
      <BaseInput v-model="email" label="邮箱" type="email" placeholder="you@example.com" autocomplete="email" />
      <BaseInput v-model="password" label="密码" type="password" placeholder="至少 8 位" autocomplete="new-password" />
      <BaseInput v-model="confirm" label="确认密码" type="password" placeholder="再次输入密码" autocomplete="new-password" />

      <div class="!mt-6 border-t border-line pt-5">
        <p class="mb-1 text-sm font-medium text-fg">设置密保问题</p>
        <p class="mb-4 text-xs text-fg-faint">用于忘记密码时找回账号，请如实填写。</p>
        <SecurityQuestionsForm v-model="questions" />
      </div>

      <FormError :message="error" />
      <BaseButton type="submit" size="lg" block :loading="loading">注册</BaseButton>
    </form>
    <template #footer>
      <p>
        已有账号？
        <router-link to="/login" class="font-medium text-accent hover:underline">去登录</router-link>
      </p>
    </template>
  </AuthLayout>
</template>
