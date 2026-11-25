<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { usePostsStore } from "../stores/posts";
import AppIcon from "../components/ui/AppIcon.vue";
import Spinner from "../components/ui/Spinner.vue";

const router = useRouter();
const auth = useAuthStore();
const posts = usePostsStore();

const title = ref("");
const content = ref("");
const tagsRaw = ref("");
const publishing = ref(false);
const error = ref<string | null>(null);

const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
const canPublish = computed(() => content.value.trim().length > 0 && !publishing.value);

const parsedTags = computed(() =>
  tagsRaw.value
    .split(/[,，\s#]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 6),
);

function goBack() {
  void router.push({ name: "posts" });
}

async function publish() {
  const cleaned = content.value.trim();
  if (!cleaned || publishing.value) return;
  publishing.value = true;
  error.value = null;
  try {
    await posts.createUserPost({
      title: title.value.trim(),
      content: cleaned,
      tags: parsedTags.value,
    });
    void router.push({ name: "posts" });
  } catch (e: any) {
    error.value = e?.detail?.detail || e?.message || "发布失败，请稍后重试";
    publishing.value = false;
  }
}
</script>

<template>
  <div class="relative flex min-w-0 flex-1 flex-col bg-canvas">
    <!-- Top Bar -->
    <header class="flex shrink-0 items-center justify-between border-b border-line/65 px-4 py-3 sm:px-6">
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="focus-ring flex h-9 w-9 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          aria-label="返回动态"
          @click="goBack"
        >
          <AppIcon name="chevron-left" class="h-5 w-5" :stroke-width="2" />
        </button>
        <h1 class="text-[16px] font-semibold text-fg">发布私人动态</h1>
      </div>

      <button
        type="button"
        class="focus-ring inline-flex h-9 items-center justify-center gap-1.5 rounded-full bg-primary px-5 text-[13.5px] font-semibold text-primary-fg transition-opacity hover:opacity-90 disabled:opacity-45"
        :disabled="!canPublish"
        @click="publish"
      >
        <Spinner v-if="publishing" class="h-3.5 w-3.5" />
        <span>{{ publishing ? "发布中..." : "发布" }}</span>
      </button>
    </header>

    <!-- Full-page Editor -->
    <div v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8 lg:px-12">
      <div class="mx-auto flex w-full max-w-4xl flex-col gap-5">
        <div
          v-if="error"
          class="rounded-2xl border border-danger/30 bg-danger-weak px-4 py-3 text-[13px] text-danger"
        >
          {{ error }}
        </div>

        <input
          v-model="title"
          type="text"
          maxlength="120"
          placeholder="标题（可选）"
          class="w-full border-b border-line/65 bg-transparent pb-3 text-[20px] font-bold text-fg placeholder:text-fg-faint focus:border-line-strong focus:outline-none"
        />

        <textarea
          v-model="content"
          rows="12"
          maxlength="4000"
          autofocus
          placeholder="写下此刻的想法、灵感、近期计划，或想让助手持续关注的话题（支持 Markdown）……"
          class="min-h-[280px] w-full resize-y bg-transparent text-[15.5px] leading-relaxed text-fg placeholder:text-fg-faint focus:outline-none"
        />

        <div class="space-y-2.5 border-t border-line/65 pt-4">
          <div class="flex flex-wrap items-center gap-2">
            <input
              v-model="tagsRaw"
              type="text"
              maxlength="120"
              placeholder="添加标签（空格或逗号分隔，最多 6 个，可选）"
              class="focus-ring min-w-[220px] flex-1 rounded-xl border border-line/80 bg-surface/60 px-3.5 py-2 text-[13px] text-fg placeholder:text-fg-faint"
            />
            <span class="text-[12px] tabular-nums text-fg-faint">
              {{ content.length }} / 4000
            </span>
          </div>

          <div v-if="parsedTags.length > 0" class="flex flex-wrap gap-1.5">
            <span
              v-for="tag in parsedTags"
              :key="tag"
              class="rounded-full bg-surface px-2.5 py-0.5 text-[12px] text-fg-muted"
            >
              #{{ tag }}
            </span>
          </div>

          <p class="text-[12.5px] text-fg-faint">
            严格仅自己可见 · 发布后自动沉淀至长期记忆 · {{ assistantName }} 稍后会来看并互动
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
