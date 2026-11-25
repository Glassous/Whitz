<script setup lang="ts">
import { computed, ref } from "vue";
import { useAuthStore } from "../../stores/auth";
import type { PostCommentItem, PostItem } from "../../types";
import MarkdownRenderer from "../chat/MarkdownRenderer.vue";
import AppIcon from "../ui/AppIcon.vue";
import BaseBadge from "../ui/BaseBadge.vue";
import BaseButton from "../ui/BaseButton.vue";
import Spinner from "../ui/Spinner.vue";

const props = defineProps<{
  post: PostItem;
}>();

const emit = defineEmits<{
  like: [string];
  bookmark: [string];
  delete: [string];
  discuss: [string];
  comment: [string, { content: string; reply_to_id?: string | null; trigger_ai_reply: boolean }];
  "delete-comment": [string, string];
}>();

const auth = useAuthStore();
const commentsOpen = ref(props.post.comments.length > 0);
const sourcesExpanded = ref(false);
const commentInput = ref("");
const replyTarget = ref<PostCommentItem | null>(null);
const triggerAiReply = ref(true);
const submittingComment = ref(false);
const scheduledHint = ref<string | null>(null);
const confirmingDelete = ref(false);

const assistantName = computed(() => auth.user?.assistant_name?.trim() || "Whitz");
const assistantAvatarUrl = computed(() => auth.user?.assistant_avatar_url ?? null);
const userDisplayName = computed(() => auth.user?.display_name?.trim() || "我");
const userAvatarUrl = computed(() => auth.user?.avatar_url ?? null);

const isAiPost = computed(() => props.post.author_type === "ai");
const authorName = computed(() => (isAiPost.value ? assistantName.value : userDisplayName.value));
const authorAvatar = computed(() => (isAiPost.value ? assistantAvatarUrl.value : userAvatarUrl.value));
const authorInitial = computed(() => authorName.value.slice(0, 1).toUpperCase() || "W");

const POST_KIND_LABELS: Record<string, string> = {
  opinion: "观点",
  digest: "资讯速递",
  insight: "深度观察",
  inspiration: "灵感推荐",
  note: "我的动态",
};

const kindLabel = computed(() => POST_KIND_LABELS[props.post.post_kind] || (isAiPost.value ? "动态" : "我的动态"));

const visibleSources = computed(() => {
  const list = props.post.web_sources || [];
  return sourcesExpanded.value ? list : list.slice(0, 2);
});

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = Date.now();
  const diffMin = Math.floor((now - d.getTime()) / 60000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} 小时前`;
  return d.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function startReply(comment: PostCommentItem) {
  commentsOpen.value = true;
  replyTarget.value = comment;
}

function clearReply() {
  replyTarget.value = null;
}

async function submitComment() {
  const text = commentInput.value.trim();
  if (!text || submittingComment.value) return;
  submittingComment.value = true;
  scheduledHint.value = null;
  try {
    emit("comment", props.post.id, {
      content: text,
      reply_to_id: replyTarget.value?.id ?? null,
      trigger_ai_reply: triggerAiReply.value,
    });
    commentInput.value = "";
    replyTarget.value = null;
    if (triggerAiReply.value && auth.user?.ai_posts_enabled) {
      scheduledHint.value = `已发布，${assistantName.value} 稍后会来看并回复你`;
    }
  } finally {
    submittingComment.value = false;
  }
}

function commentAuthorLabel(authorType: "user" | "ai"): string {
  return authorType === "ai" ? assistantName.value : userDisplayName.value;
}
</script>

<template>
  <article class="post-card rounded-[24px] border border-line/75 bg-canvas p-5 transition-colors hover:border-line-strong/80 dark:bg-sidebar/75">
    <!-- Header -->
    <div class="flex items-start justify-between gap-3">
      <div class="flex min-w-0 items-center gap-3">
        <img
          v-if="authorAvatar"
          :src="authorAvatar"
          alt=""
          class="h-10 w-10 shrink-0 rounded-full bg-surface object-cover ring-1 ring-line"
        />
        <span
          v-else
          class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[13.5px] font-semibold ring-1 ring-line"
          :class="isAiPost ? 'bg-primary text-primary-fg' : 'bg-surface text-fg'"
        >
          {{ authorInitial }}
        </span>

        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="truncate text-[14.5px] font-semibold text-fg">{{ authorName }}</span>
            <BaseBadge :tone="isAiPost ? 'brand' : 'gray'">{{ kindLabel }}</BaseBadge>
            <BaseBadge v-if="post.source_collection_name" tone="gray">
              记忆 · {{ post.source_collection_name }}
            </BaseBadge>
            <BaseBadge v-else-if="!isAiPost && post.memory_entry_id" tone="gray">
              已同步记忆
            </BaseBadge>
          </div>
          <p class="mt-0.5 text-[12px] text-fg-faint">{{ formatTime(post.created_at) }} · 仅自己可见</p>
        </div>
      </div>

      <!-- Delete control -->
      <div class="flex shrink-0 items-center gap-1">
        <template v-if="confirmingDelete">
          <BaseButton size="sm" variant="danger" @click="emit('delete', post.id)">确认删除</BaseButton>
          <BaseButton size="sm" variant="ghost" @click="confirmingDelete = false">取消</BaseButton>
        </template>
        <button
          v-else
          type="button"
          class="focus-ring flex h-8 w-8 items-center justify-center rounded-lg text-fg-faint transition-colors hover:bg-hover hover:text-danger"
          aria-label="删除动态"
          title="删除动态"
          @click="confirmingDelete = true"
        >
          <AppIcon name="trash" class="h-4 w-4" :stroke-width="1.85" />
        </button>
      </div>
    </div>

    <!-- Title & Markdown Body -->
    <div class="mt-3.5 space-y-2">
      <h3 v-if="post.title" class="text-[16px] font-semibold leading-snug text-fg">
        {{ post.title }}
      </h3>
      <div class="prose-post text-[14.5px] leading-relaxed text-fg/95">
        <MarkdownRenderer :content="post.content" />
      </div>
    </div>

    <!-- Tags -->
    <div v-if="post.tags.length > 0" class="mt-3 flex flex-wrap gap-1.5">
      <span
        v-for="tag in post.tags"
        :key="tag"
        class="rounded-full bg-surface px-2.5 py-0.5 text-[12px] text-fg-muted"
      >
        #{{ tag }}
      </span>
    </div>

    <!-- Web Search Sources (for web-grounded AI posts) -->
    <div
      v-if="post.web_sources && post.web_sources.length > 0"
      class="mt-3.5 rounded-2xl border border-line/70 bg-surface/60 p-3"
    >
      <div class="flex items-center justify-between gap-2 text-[12px] font-medium text-fg-muted">
        <span class="inline-flex items-center gap-1.5">
          <AppIcon name="globe" class="h-3.5 w-3.5" :stroke-width="1.9" />
          联网参考来源（{{ post.web_sources.length }}）
        </span>
        <button
          v-if="post.web_sources.length > 2"
          type="button"
          class="text-[11.5px] text-fg-faint hover:text-fg"
          @click="sourcesExpanded = !sourcesExpanded"
        >
          {{ sourcesExpanded ? "收起" : "展开全部" }}
        </button>
      </div>
      <div class="mt-2 space-y-1.5">
        <a
          v-for="(src, idx) in visibleSources"
          :key="src.url + idx"
          :href="src.url"
          target="_blank"
          rel="noopener noreferrer"
          class="group flex items-center justify-between gap-2 rounded-xl px-2.5 py-1.5 text-[12.5px] transition-colors hover:bg-hover/80"
        >
          <span class="min-w-0 truncate text-fg group-hover:underline">{{ src.title || src.url }}</span>
          <span class="flex shrink-0 items-center gap-1 text-[11px] text-fg-faint">
            <span v-if="src.site_name">{{ src.site_name }}</span>
            <AppIcon name="external-link" class="h-3 w-3" />
          </span>
        </a>
      </div>
    </div>

    <!-- AI Liked Badge (for user posts) -->
    <div
      v-if="post.ai_liked"
      class="mt-3 inline-flex items-center gap-1.5 rounded-full bg-surface px-3 py-1 text-[12px] text-fg-muted ring-1 ring-line/80"
    >
      <AppIcon name="heart" class="h-3.5 w-3.5 text-danger" :stroke-width="2" />
      <span>{{ assistantName }} 赞了这条动态</span>
    </div>

    <!-- Action Bar -->
    <div class="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line/60 pt-3">
      <div class="flex items-center gap-1.5">
        <button
          type="button"
          class="focus-ring inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors"
          :class="post.is_liked ? 'bg-danger-weak text-danger' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @click="emit('like', post.id)"
        >
          <AppIcon name="heart" :active="post.is_liked" class="h-4 w-4" :stroke-width="1.9" />
          <span>{{ post.is_liked ? "已赞" : "点赞" }}</span>
        </button>

        <button
          type="button"
          class="focus-ring inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium transition-colors"
          :class="post.is_bookmarked ? 'bg-warning-weak text-warning' : 'text-fg-muted hover:bg-hover hover:text-fg'"
          @click="emit('bookmark', post.id)"
        >
          <AppIcon name="bookmark" :active="post.is_bookmarked" class="h-4 w-4" :stroke-width="1.9" />
          <span>{{ post.is_bookmarked ? "已收藏" : "收藏" }}</span>
        </button>

        <button
          type="button"
          class="focus-ring inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[12.5px] font-medium text-fg-muted transition-colors hover:bg-hover hover:text-fg"
          @click="commentsOpen = !commentsOpen"
        >
          <AppIcon name="message-dots" class="h-4 w-4" :stroke-width="1.9" />
          <span>评论{{ post.comment_count > 0 ? ` (${post.comment_count})` : "" }}</span>
        </button>
      </div>

      <button
        type="button"
        class="focus-ring inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/80 px-3 py-1.5 text-[12.5px] font-medium text-fg transition-colors hover:bg-hover"
        @click="emit('discuss', post.id)"
      >
        <AppIcon name="chat" class="h-3.5 w-3.5" :stroke-width="1.95" />
        <span>转去聊天</span>
      </button>
    </div>

    <!-- Comments Section -->
    <div v-if="commentsOpen" class="mt-3.5 space-y-3 border-t border-line/60 pt-3.5">
      <div v-if="post.comments.length > 0" class="space-y-2.5">
        <div
          v-for="c in post.comments"
          :key="c.id"
          class="group rounded-2xl bg-surface/70 px-3.5 py-2.5 text-[13px]"
        >
          <div class="flex items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5">
              <span class="font-semibold text-fg">{{ commentAuthorLabel(c.author_type) }}</span>
              <span
                v-if="c.author_type === 'ai'"
                class="rounded-full bg-canvas px-1.5 py-0.5 text-[10px] font-medium text-fg-faint ring-1 ring-line"
              >
                AI
              </span>
              <span v-if="c.reply_to_author_type" class="text-[11.5px] text-fg-faint">
                回复 {{ commentAuthorLabel(c.reply_to_author_type) }}
              </span>
              <span class="text-[11px] text-fg-faint">· {{ formatTime(c.created_at) }}</span>
            </div>
            <div class="flex items-center gap-2 opacity-80 transition-opacity group-hover:opacity-100">
              <button
                type="button"
                class="text-[11.5px] font-medium text-fg-faint hover:text-fg"
                @click="startReply(c)"
              >
                回复
              </button>
              <button
                type="button"
                class="text-[11.5px] text-fg-faint hover:text-danger"
                @click="emit('delete-comment', post.id, c.id)"
              >
                删除
              </button>
            </div>
          </div>

          <p
            v-if="c.reply_to_excerpt"
            class="mt-1 border-l-2 border-line-strong pl-2 text-[11.5px] text-fg-faint"
          >
            {{ c.reply_to_excerpt }}
          </p>

          <p class="mt-1 whitespace-pre-wrap leading-relaxed text-fg/90">{{ c.content }}</p>

          <div v-if="c.ai_liked" class="mt-1.5 inline-flex items-center gap-1 text-[11px] text-fg-faint">
            <AppIcon name="heart" class="h-3 w-3 text-danger" />
            <span>{{ assistantName }} 赞了这条评论</span>
          </div>
        </div>
      </div>

      <!-- Reply target indicator -->
      <div
        v-if="replyTarget"
        class="flex items-center justify-between gap-2 rounded-xl bg-hover/70 px-3 py-1.5 text-[12px] text-fg-muted"
      >
        <span class="truncate">
          正在回复 <strong class="text-fg">{{ commentAuthorLabel(replyTarget.author_type) }}</strong>：{{ replyTarget.content }}
        </span>
        <button type="button" class="shrink-0 text-fg-faint hover:text-fg" @click="clearReply">
          <AppIcon name="close" class="h-3.5 w-3.5" />
        </button>
      </div>

      <!-- Comment Input -->
      <form class="space-y-2" @submit.prevent="submitComment">
        <div class="flex items-center gap-2">
          <input
            v-model="commentInput"
            type="text"
            maxlength="2000"
            :placeholder="replyTarget ? `回复 ${commentAuthorLabel(replyTarget.author_type)}...` : '写下你的想法，后续 AI 发帖也会参考...'"
            class="focus-ring min-w-0 flex-1 rounded-full border border-line bg-canvas px-4 py-2 text-[13px] text-fg placeholder:text-fg-faint"
          />
          <BaseButton type="submit" size="sm" :disabled="!commentInput.trim() || submittingComment">
            <Spinner v-if="submittingComment" class="h-3.5 w-3.5" />
            <span v-else>发送</span>
          </BaseButton>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-2 px-1 text-[11.5px] text-fg-faint">
          <label class="inline-flex cursor-pointer select-none items-center gap-1.5">
            <input v-model="triggerAiReply" type="checkbox" class="h-3.5 w-3.5 rounded accent-primary" />
            <span>邀请 {{ assistantName }} 稍后回复（消耗少量积分）</span>
          </label>
          <span v-if="scheduledHint" class="text-success">{{ scheduledHint }}</span>
        </div>
      </form>
    </div>
  </article>
</template>
