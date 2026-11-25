<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/auth";
import type { User, UserFeedbackItem } from "../../types";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import BaseTextarea from "../ui/BaseTextarea.vue";

const auth = useAuthStore();

const RATING_CHOICES = [
  { value: 1, emoji: "😞", label: "很不满意" },
  { value: 2, emoji: "😕", label: "有待改善" },
  { value: 3, emoji: "😐", label: "一般般" },
  { value: 4, emoji: "😊", label: "比较满意" },
  { value: 5, emoji: "🥰", label: "非常棒" },
];

const CATEGORIES = [
  { value: "general", label: "整体体验" },
  { value: "quality", label: "回答质量" },
  { value: "speed", label: "响应速度" },
  { value: "ui", label: "界面交互" },
  { value: "feature", label: "功能建议" },
  { value: "bug", label: "问题反馈" },
] as const;

const rating = ref(5);
const category = ref<(typeof CATEGORIES)[number]["value"]>("general");
const content = ref("");
const submitting = ref(false);
const savingToggle = ref(false);
const savingPostsToggle = ref(false);
const loadingHistory = ref(false);
const feedbackList = ref<UserFeedbackItem[]>([]);
const message = ref<string | null>(null);
const error = ref<string | null>(null);

async function loadFeedbacks() {
  loadingHistory.value = true;
  try {
    feedbackList.value = await api.get<UserFeedbackItem[]>("/users/me/feedback");
  } catch {
    /* ignore initial load errors */
  } finally {
    loadingHistory.value = false;
  }
}

async function toggleAiReactions() {
  if (!auth.user || savingToggle.value) return;
  savingToggle.value = true;
  error.value = null;
  const nextVal = !(auth.user.ai_reactions_enabled ?? true);
  try {
    const updated = await api.put<User>("/users/me/ai-reactions", {
      ai_reactions_enabled: nextVal,
    });
    auth.user = updated;
    message.value = nextVal ? "已开启 AI 正向点赞互动" : "已关闭 AI 正向点赞互动";
  } catch (e: any) {
    error.value = e?.message || "更新偏好失败";
  } finally {
    savingToggle.value = false;
  }
}

async function toggleAiPosts() {
  if (!auth.user || savingPostsToggle.value) return;
  savingPostsToggle.value = true;
  error.value = null;
  const nextVal = !(auth.user.ai_posts_enabled ?? false);
  try {
    const updated = await api.put<User>("/users/me/ai-posts", {
      ai_posts_enabled: nextVal,
    });
    auth.user = updated;
    message.value = nextVal
      ? "已开启 AI 每日联网动态（正常消耗账号积分）"
      : "已关闭 AI 每日联网动态";
  } catch (e: any) {
    error.value = e?.message || "更新偏好失败";
  } finally {
    savingPostsToggle.value = false;
  }
}

async function submitFeedback() {
  const cleaned = content.value.trim();
  if (!cleaned || submitting.value) return;
  submitting.value = true;
  error.value = null;
  message.value = null;
  try {
    const created = await api.post<UserFeedbackItem>("/users/me/feedback", {
      rating: rating.value,
      category: category.value,
      content: cleaned,
    });
    feedbackList.value = [created, ...feedbackList.value];
    content.value = "";
    rating.value = 5;
    message.value = "感谢你的评价与反馈！我们会持续改进产品体验。";
  } catch (e: any) {
    error.value = e?.detail?.detail || e?.message || "提交失败，请稍后重试";
  } finally {
    submitting.value = false;
  }
}

function statusLabel(status: string): string {
  if (status === "resolved") return "已解决";
  if (status === "reviewed") return "已查看";
  return "待处理";
}

function statusTone(status: string): "green" | "blue" | "gray" {
  if (status === "resolved") return "green";
  if (status === "reviewed") return "blue";
  return "gray";
}

function categoryLabel(cat: string): string {
  return CATEGORIES.find((c) => c.value === cat)?.label ?? cat;
}

onMounted(() => {
  void loadFeedbacks();
});
</script>

<template>
  <div class="space-y-5">
    <!-- AI Positive Reaction Preference -->
    <div class="flex flex-wrap items-center justify-between gap-4 rounded-[24px] bg-sidebar p-5 dark:bg-surface">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <p class="text-[15px] font-semibold text-fg">AI 正向互动点赞</p>
          <BaseBadge tone="brand">仅正向激励</BaseBadge>
        </div>
        <p class="mt-1 text-[13px] leading-relaxed text-fg-muted">
          开启后，当你在对话中提出有洞察的问题或清晰思路时，助手可能会给你的消息送上 👍、❤️、✨ 或 💡 等正向鼓励（永不出现负面评价）。
        </p>
      </div>
      <button
        type="button"
        role="switch"
        :aria-checked="auth.user?.ai_reactions_enabled ?? true"
        :disabled="savingToggle"
        class="focus-ring relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-60"
        :class="(auth.user?.ai_reactions_enabled ?? true) ? 'bg-accent' : 'bg-line-strong'"
        @click="toggleAiReactions"
      >
        <span
          class="inline-block h-5.5 w-5.5 transform rounded-full bg-white shadow transition-transform"
          :class="(auth.user?.ai_reactions_enabled ?? true) ? 'translate-x-5.5' : 'translate-x-1'"
        />
      </button>
    </div>

    <!-- AI Daily Private Posts Preference -->
    <div class="flex flex-wrap items-center justify-between gap-4 rounded-[24px] bg-sidebar p-5 dark:bg-surface">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <p class="text-[15px] font-semibold text-fg">AI 每日联网动态</p>
          <BaseBadge tone="amber">默认关闭 · 消耗积分</BaseBadge>
        </div>
        <p class="mt-1 text-[13px] leading-relaxed text-fg-muted">
          开启后，助手将每日根据你的长期记忆分类与联网搜索结果为你生成仅自己可见的专属动态，并在你发帖或评论后间隔一段时间进行点赞与回复。上述调用均正常计入积分消耗，记忆为 0 或额度不足时自动跳过。
        </p>
      </div>
      <button
        type="button"
        role="switch"
        :aria-checked="auth.user?.ai_posts_enabled ?? false"
        :disabled="savingPostsToggle"
        class="focus-ring relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-60"
        :class="(auth.user?.ai_posts_enabled ?? false) ? 'bg-accent' : 'bg-line-strong'"
        @click="toggleAiPosts"
      >
        <span
          class="inline-block h-5.5 w-5.5 transform rounded-full bg-white shadow transition-transform"
          :class="(auth.user?.ai_posts_enabled ?? false) ? 'translate-x-5.5' : 'translate-x-1'"
        />
      </button>
    </div>

    <!-- Submit Feedback Form -->
    <div class="rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <h2 class="text-[15px] font-semibold text-fg">提交产品评价与建议</h2>
      <p class="mt-1 text-[13px] text-fg-muted">你的评分与建议会直接进入后台量化看板，帮助我们优化回答质量与功能设计。</p>

      <div class="mt-4 space-y-4">
        <div>
          <p class="mb-2 text-[12.5px] font-medium text-fg-muted">整体满意度</p>
          <div class="grid grid-cols-5 gap-2">
            <button
              v-for="opt in RATING_CHOICES"
              :key="opt.value"
              type="button"
              class="focus-ring flex flex-col items-center gap-1 rounded-2xl border px-2 py-2.5 text-center transition-colors"
              :class="
                rating === opt.value
                  ? 'border-accent bg-accent-weak/75 text-fg'
                  : 'border-line bg-canvas/70 text-fg-muted hover:bg-hover hover:text-fg'
              "
              @click="rating = opt.value"
            >
              <span class="text-xl leading-none">{{ opt.emoji }}</span>
              <span class="text-[11px] font-medium">{{ opt.label }}</span>
            </button>
          </div>
        </div>

        <div>
          <p class="mb-2 text-[12.5px] font-medium text-fg-muted">反馈分类</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="cat in CATEGORIES"
              :key="cat.value"
              type="button"
              class="focus-ring rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors"
              :class="
                category === cat.value
                  ? 'bg-primary text-primary-fg'
                  : 'bg-canvas text-fg-muted hover:bg-hover hover:text-fg'
              "
              @click="category = cat.value"
            >
              {{ cat.label }}
            </button>
          </div>
        </div>

        <div>
          <p class="mb-1.5 text-[12.5px] font-medium text-fg-muted">详细说明</p>
          <BaseTextarea
            v-model="content"
            :rows="4"
            placeholder="告诉我们你最喜欢的功能、遇到的卡顿/回答问题，或希望新增的能力…"
          />
        </div>

        <p v-if="error" class="rounded-xl bg-danger-weak px-3 py-2 text-[13px] text-danger">{{ error }}</p>
        <p v-if="message" class="rounded-xl bg-success-weak px-3 py-2 text-[13px] text-success">{{ message }}</p>

        <div class="flex justify-end">
          <BaseButton rounded="full" :loading="submitting" :disabled="!content.trim()" @click="submitFeedback">
            提交评价反馈
          </BaseButton>
        </div>
      </div>
    </div>

    <!-- Submission History -->
    <div class="rounded-[24px] bg-sidebar p-5 sm:p-6 dark:bg-surface">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-[15px] font-semibold text-fg">我的反馈记录</h2>
        <span class="text-[12px] text-fg-faint">共 {{ feedbackList.length }} 条</span>
      </div>
      <div v-if="loadingHistory" class="py-6 text-center text-[13px] text-fg-faint">加载中…</div>
      <div v-else-if="!feedbackList.length" class="py-6 text-center text-[13px] text-fg-faint">
        还没有提交过产品评价，欢迎随时分享你的体验。
      </div>
      <div v-else class="space-y-3">
        <div
          v-for="item in feedbackList"
          :key="item.id"
          class="rounded-2xl border border-line bg-canvas/80 p-3.5"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-[12.5px]">
              <span>{{ RATING_CHOICES.find((r) => r.value === item.rating)?.emoji ?? "😊" }}</span>
              <span class="font-medium text-fg">{{ item.rating }}/5</span>
              <BaseBadge tone="gray">{{ categoryLabel(item.category) }}</BaseBadge>
              <BaseBadge :tone="statusTone(item.status)">{{ statusLabel(item.status) }}</BaseBadge>
            </div>
            <span class="text-[11.5px] text-fg-faint">{{ new Date(item.created_at).toLocaleString() }}</span>
          </div>
          <p class="mt-2 whitespace-pre-wrap text-[13.5px] leading-relaxed text-fg">{{ item.content }}</p>
          <div v-if="item.admin_note" class="mt-2 rounded-xl bg-surface px-3 py-2 text-[12.5px] text-fg-muted">
            <span class="font-medium text-fg">官方回复：</span>{{ item.admin_note }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
