<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../../stores/auth";
import { usePostsStore, type PostFeedFilter } from "../../stores/posts";
import AppIcon from "../ui/AppIcon.vue";
import BaseButton from "../ui/BaseButton.vue";
import Spinner from "../ui/Spinner.vue";
import PostCard from "./PostCard.vue";
import PostsOnboardingView from "./PostsOnboardingView.vue";

const emit = defineEmits<{
  "open-mobile-nav": [];
  "open-guide": [];
  "open-compose": [];
  "discuss-in-chat": [{ conversationId: string; prefillPrompt: string }];
}>();

const router = useRouter();
const auth = useAuthStore();
const posts = usePostsStore();

const togglingEnable = ref(false);
const actionError = ref<string | null>(null);

const isEnabled = computed(() => Boolean(auth.user?.ai_posts_enabled));
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

const filters: { key: PostFeedFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "ai", label: "AI 动态" },
  { key: "user", label: "我的" },
  { key: "bookmarked", label: "已收藏" },
];

onMounted(() => {
  posts.markRead();
  if (isEnabled.value) {
    void posts.fetchFeed(true);
  } else {
    void posts.fetchQuota();
  }
});

async function onEnablePosts() {
  if (togglingEnable.value) return;
  togglingEnable.value = true;
  actionError.value = null;
  try {
    await posts.setAiPostsEnabled(true);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "开启失败，请稍后重试";
  } finally {
    togglingEnable.value = false;
  }
}

async function handleLike(postId: string) {
  try {
    await posts.toggleLike(postId);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "操作失败";
  }
}

async function handleBookmark(postId: string) {
  try {
    await posts.toggleBookmark(postId);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "操作失败";
  }
}

async function handleDelete(postId: string) {
  try {
    await posts.deletePost(postId);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "删除失败";
  }
}

async function handleComment(
  postId: string,
  payload: { content: string; reply_to_id?: string | null; trigger_ai_reply: boolean },
) {
  try {
    await posts.addComment(postId, payload);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "评论发送失败";
  }
}

async function handleDeleteComment(postId: string, commentId: string) {
  try {
    await posts.deleteComment(postId, commentId);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "删除评论失败";
  }
}

async function handleDiscuss(postId: string) {
  try {
    const res = await posts.discussInChat(postId);
    emit("discuss-in-chat", {
      conversationId: res.conversation_id,
      prefillPrompt: res.prefill_prompt,
    });
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "转去聊天失败";
  }
}

function goMemorySettings() {
  void router.push({ name: "settings", query: { tab: "memory" } });
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col bg-canvas">
    <!-- Disabled State: Full-area minimal onboarding -->
    <template v-if="!isEnabled">
      <div class="flex shrink-0 items-center justify-between border-b border-line/60 px-4 py-3 md:hidden">
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="focus-ring flex h-9 w-9 items-center justify-center rounded-xl text-fg-muted hover:bg-hover hover:text-fg"
            aria-label="打开导航"
            @click="emit('open-mobile-nav')"
          >
            <AppIcon name="menu-lines" class="h-[20px] w-[20px]" :stroke-width="2.1" />
          </button>
          <h1 class="text-[16px] font-semibold text-fg">动态</h1>
        </div>
        <button
          type="button"
          class="focus-ring inline-flex items-center gap-1 rounded-full px-3 py-1 text-[12.5px] font-medium text-fg-muted hover:bg-hover hover:text-fg"
          @click="emit('open-guide')"
        >
          <AppIcon name="info" class="h-4 w-4" />
          <span>说明</span>
        </button>
      </div>
      <PostsOnboardingView
        :enabling="togglingEnable"
        @enable="onEnablePosts"
        @open-guide="emit('open-guide')"
      />
    </template>

    <!-- Enabled State: Full-width feed -->
    <div v-else v-scrollbar class="custom-scrollbar min-h-0 flex-1 overflow-y-auto">
      <div class="flex min-h-full w-full flex-col">
        <!-- Sticky Frosted Top Bar + Tabs -->
        <header class="sticky top-0 z-20 border-b border-line/65 bg-canvas/85 backdrop-blur-md">
          <div class="flex items-center justify-between px-4 py-2.5 sm:px-6 lg:px-8">
            <div class="flex items-center gap-2.5">
              <button
                type="button"
                class="focus-ring flex h-9 w-9 items-center justify-center rounded-full text-fg-muted hover:bg-hover hover:text-fg md:hidden"
                aria-label="打开导航"
                @click="emit('open-mobile-nav')"
              >
                <AppIcon name="menu-lines" class="h-[20px] w-[20px]" :stroke-width="2.1" />
              </button>
              <h1 class="text-[17px] font-bold tracking-tight text-fg">动态</h1>
            </div>

            <div class="flex items-center gap-1.5">
              <button
                type="button"
                class="focus-ring inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                title="查看动态说明与配额"
                @click="emit('open-guide')"
              >
                <AppIcon name="info" class="h-4 w-4" :stroke-width="1.85" />
                <span>说明</span>
              </button>
              <button
                type="button"
                class="focus-ring flex h-8 w-8 items-center justify-center rounded-full text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                aria-label="刷新"
                title="刷新"
                :disabled="posts.loading"
                @click="posts.fetchFeed(true)"
              >
                <AppIcon name="refresh" class="h-4 w-4" :class="posts.loading ? 'animate-spin' : ''" />
              </button>
              <button
                type="button"
                class="focus-ring inline-flex h-8.5 items-center gap-1.5 rounded-full bg-primary px-4 text-[13px] font-semibold text-primary-fg transition-opacity hover:opacity-90"
                @click="emit('open-compose')"
              >
                <AppIcon name="plus" class="h-4 w-4" :stroke-width="2.2" />
                <span>发帖</span>
              </button>
            </div>
          </div>

          <!-- 4-way Underline Tabs -->
          <div class="grid grid-cols-4 px-2 sm:px-6 lg:px-8">
            <button
              v-for="f in filters"
              :key="f.key"
              type="button"
              class="focus-ring relative flex h-11 items-center justify-center text-[13.5px] font-medium transition-colors hover:bg-hover/50"
              :class="posts.filter === f.key ? 'font-semibold text-fg' : 'text-fg-muted'"
              @click="posts.setFilter(f.key)"
            >
              <span>{{ f.label }}</span>
              <span
                v-if="posts.filter === f.key"
                class="absolute bottom-0 h-[3px] w-14 rounded-full bg-fg"
                aria-hidden="true"
              />
            </button>
          </div>
        </header>

        <!-- Compact 0-memory Notice Strip -->
        <div
          v-if="posts.quota && posts.quota.memory_entry_count === 0"
          class="flex items-center justify-between gap-3 border-b border-line/65 bg-surface/55 px-4 py-2.5 text-[12.5px] text-fg-muted sm:px-6 lg:px-8"
        >
          <span>当前长期记忆为 0，{{ assistantName }} 今日将发 0 条。</span>
          <button
            type="button"
            class="shrink-0 font-medium text-fg hover:underline"
            @click="goMemorySettings"
          >
            添加记忆 →
          </button>
        </div>

        <!-- Error Strip -->
        <div
          v-if="actionError || posts.error"
          class="border-b border-danger/25 bg-danger-weak px-4 py-2.5 text-[13px] text-danger sm:px-6 lg:px-8"
        >
          {{ actionError || posts.error }}
        </div>

        <!-- Timeline Stream -->
        <div v-if="posts.loading && posts.items.length === 0" class="flex flex-1 items-center justify-center py-20 text-fg-faint">
          <Spinner class="h-6 w-6" />
        </div>

        <div v-else-if="posts.items.length === 0" class="px-6 py-20 text-center">
          <p class="text-[15px] font-semibold text-fg">还没有动态</p>
          <p class="mt-1.5 text-[13px] text-fg-muted">
            点击右上角「发帖」记录你的私人想法，或等待 {{ assistantName }} 每日联网为你更新。
          </p>
          <button
            type="button"
            class="focus-ring mt-5 inline-flex h-9 items-center gap-1.5 rounded-full bg-primary px-5 text-[13px] font-semibold text-primary-fg transition-opacity hover:opacity-90"
            @click="emit('open-compose')"
          >
            <AppIcon name="plus" class="h-4 w-4" :stroke-width="2.2" />
            <span>写第一条私人动态</span>
          </button>
        </div>

        <template v-else>
          <PostCard
            v-for="item in posts.items"
            :key="item.id"
            :post="item"
            @like="handleLike"
            @bookmark="handleBookmark"
            @delete="handleDelete"
            @discuss="handleDiscuss"
            @comment="handleComment"
            @delete-comment="handleDeleteComment"
          />

          <div v-if="posts.nextCursor" class="flex justify-center py-6">
            <BaseButton variant="ghost" size="sm" :disabled="posts.loadingMore" @click="posts.fetchFeed(false)">
              <Spinner v-if="posts.loadingMore" class="mr-1.5 h-3.5 w-3.5" />
              <span>{{ posts.loadingMore ? "加载中..." : "加载更多" }}</span>
            </BaseButton>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
