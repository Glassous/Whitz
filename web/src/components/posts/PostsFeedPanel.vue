<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../../stores/auth";
import { usePostsStore, type PostFeedFilter } from "../../stores/posts";
import AppIcon from "../ui/AppIcon.vue";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import Spinner from "../ui/Spinner.vue";
import PostCard from "./PostCard.vue";
import PostsOnboardingView from "./PostsOnboardingView.vue";

const emit = defineEmits<{
  "discuss-in-chat": [{ conversationId: string; prefillPrompt: string }];
}>();

const router = useRouter();
const auth = useAuthStore();
const posts = usePostsStore();

const togglingEnable = ref(false);
const composerTitle = ref("");
const composerContent = ref("");
const composerTagsRaw = ref("");
const publishing = ref(false);
const publishHint = ref<string | null>(null);
const actionError = ref<string | null>(null);

const isEnabled = computed(() => Boolean(auth.user?.ai_posts_enabled));
const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");

const filters: { key: PostFeedFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "ai", label: "AI 动态" },
  { key: "user", label: "我的动态" },
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

async function onDisablePosts() {
  if (togglingEnable.value) return;
  togglingEnable.value = true;
  actionError.value = null;
  try {
    await posts.setAiPostsEnabled(false);
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "关闭失败，请稍后重试";
  } finally {
    togglingEnable.value = false;
  }
}

function parseTags(raw: string): string[] {
  return raw
    .split(/[,，\s#]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, 6);
}

async function publishUserPost() {
  const content = composerContent.value.trim();
  if (!content || publishing.value) return;
  publishing.value = true;
  actionError.value = null;
  publishHint.value = null;
  try {
    const created = await posts.createUserPost({
      title: composerTitle.value.trim(),
      content,
      tags: parseTags(composerTagsRaw.value),
    });
    composerTitle.value = "";
    composerContent.value = "";
    composerTagsRaw.value = "";
    publishHint.value = created.memory_entry_id
      ? `已发布并同步至长期记忆，${assistantName.value} 稍后会来互动`
      : `已发布，${assistantName.value} 稍后会来互动`;
  } catch (e: any) {
    actionError.value = e?.detail?.detail || e?.message || "发布失败，请稍后重试";
  } finally {
    publishing.value = false;
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
  <div class="space-y-5">
    <Transition
      mode="out-in"
      enter-active-class="transition duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
      enter-from-class="opacity-0 translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <!-- Disabled state: Animated Onboarding View -->
      <PostsOnboardingView
        v-if="!isEnabled"
        key="onboarding"
        :quota="posts.quota"
        :enabling="togglingEnable"
        @enable="onEnablePosts"
      />

      <!-- Enabled state: Full Private Feed -->
      <div v-else key="feed" class="space-y-5">
        <!-- Quota & Memory Status Summary -->
        <div class="rounded-[24px] border border-line/75 bg-sidebar/80 p-4 sm:p-5 dark:bg-surface/75">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="space-y-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[14.5px] font-semibold text-fg">AI 每日联网动态已开启</span>
                <BaseBadge tone="brand">{{ posts.quota?.tier_label || "Free" }}</BaseBadge>
                <BaseBadge tone="gray">
                  预计每日 {{ posts.quota?.estimated_daily_count ?? 0 }} / {{ posts.quota?.max_daily_cap ?? 2 }} 条
                </BaseBadge>
              </div>
              <p class="text-[12.5px] text-fg-muted">
                当前已启用长期记忆 {{ posts.quota?.memory_entry_count ?? 0 }} 条（覆盖 {{ posts.quota?.active_collection_count ?? 0 }} 个分类），系统将于每日后台自动联网生成，正常消耗积分额度。
              </p>
            </div>

            <div class="flex items-center gap-2">
              <BaseButton size="sm" variant="ghost" @click="goMemorySettings">
                管理记忆
              </BaseButton>
              <BaseButton size="sm" variant="ghost" :disabled="togglingEnable" @click="onDisablePosts">
                {{ togglingEnable ? "关闭中..." : "关闭功能" }}
              </BaseButton>
            </div>
          </div>

          <!-- Zero memory friendly notice -->
          <div
            v-if="posts.quota && posts.quota.memory_entry_count === 0"
            class="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-line bg-canvas/85 px-3.5 py-2.5 text-[12.5px] text-fg-muted"
          >
            <span>当前长期记忆为 0 条，{{ assistantName }} 还不知道发什么（今日将发 0 条）。发一条你的动态或去添加记忆即可唤醒它！</span>
            <button
              type="button"
              class="shrink-0 font-medium text-fg underline underline-offset-4"
              @click="goMemorySettings"
            >
              添加记忆 →
            </button>
          </div>
        </div>

        <!-- User Private Post Composer -->
        <form
          class="rounded-[24px] border border-line/75 bg-canvas p-4 sm:p-5 dark:bg-sidebar/75"
          @submit.prevent="publishUserPost"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="text-[13.5px] font-semibold text-fg">记录一条私人动态</span>
            <span class="text-[11.5px] text-fg-faint">仅自己可见 · 自动同步至长期记忆</span>
          </div>
          <input
            v-model="composerTitle"
            type="text"
            maxlength="120"
            placeholder="标题（可选）"
            class="focus-ring mt-2.5 w-full rounded-xl border border-line/80 bg-surface/60 px-3.5 py-2 text-[13.5px] text-fg placeholder:text-fg-faint"
          />
          <textarea
            v-model="composerContent"
            rows="3"
            maxlength="4000"
            placeholder="分享你此刻的想法、灵感、近期计划或想追踪的话题……"
            class="focus-ring mt-2 w-full resize-none rounded-xl border border-line/80 bg-surface/60 px-3.5 py-2.5 text-[13.5px] leading-relaxed text-fg placeholder:text-fg-faint"
          />
          <div class="mt-2.5 flex flex-wrap items-center justify-between gap-2.5">
            <input
              v-model="composerTagsRaw"
              type="text"
              maxlength="120"
              placeholder="标签（空格或逗号分隔，可选）"
              class="focus-ring min-w-[180px] flex-1 rounded-full border border-line/80 bg-surface/60 px-3.5 py-1.5 text-[12.5px] text-fg placeholder:text-fg-faint"
            />
            <BaseButton type="submit" size="sm" :disabled="!composerContent.trim() || publishing">
              <Spinner v-if="publishing" class="h-3.5 w-3.5" />
              <span v-else>发布动态</span>
            </BaseButton>
          </div>
          <p v-if="publishHint" class="mt-2 text-[12px] text-success">{{ publishHint }}</p>
        </form>

        <!-- Error Banner -->
        <div
          v-if="actionError || posts.error"
          class="rounded-2xl border border-danger/30 bg-danger-weak px-4 py-2.5 text-[13px] text-danger"
        >
          {{ actionError || posts.error }}
        </div>

        <!-- Filter Bar -->
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div class="inline-flex items-center gap-1 rounded-full border border-line bg-surface/70 p-1">
            <button
              v-for="f in filters"
              :key="f.key"
              type="button"
              class="focus-ring rounded-full px-3.5 py-1 text-[12.5px] font-medium transition-colors"
              :class="
                posts.filter === f.key
                  ? 'bg-canvas text-fg shadow-xs dark:bg-active'
                  : 'text-fg-muted hover:text-fg'
              "
              @click="posts.setFilter(f.key)"
            >
              {{ f.label }}
            </button>
          </div>

          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] text-fg-muted transition-colors hover:bg-hover hover:text-fg"
            :disabled="posts.loading"
            @click="posts.fetchFeed(true)"
          >
            <AppIcon name="refresh" class="h-3.5 w-3.5" :class="posts.loading ? 'animate-spin' : ''" />
            <span>刷新</span>
          </button>
        </div>

        <!-- Feed List -->
        <div v-if="posts.loading && posts.items.length === 0" class="flex items-center justify-center py-16 text-fg-faint">
          <Spinner class="h-6 w-6" />
        </div>

        <div
          v-else-if="posts.items.length === 0"
          class="rounded-[24px] border border-dashed border-line-strong/80 bg-surface/40 px-6 py-14 text-center"
        >
          <p class="text-[15px] font-medium text-fg">这里暂时还没有动态</p>
          <p class="mt-1.5 text-[13px] text-fg-muted">
            你可以先在上方写下第一条私人动态，{{ assistantName }} 也会在每日后台自动结合你的记忆与联网搜索为你更新动态。
          </p>
        </div>

        <div v-else class="space-y-4">
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

          <div v-if="posts.nextCursor" class="flex justify-center pt-2">
            <BaseButton variant="ghost" :disabled="posts.loadingMore" @click="posts.fetchFeed(false)">
              <Spinner v-if="posts.loadingMore" class="mr-1.5 h-3.5 w-3.5" />
              <span>{{ posts.loadingMore ? "加载中..." : "加载更多动态" }}</span>
            </BaseButton>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
