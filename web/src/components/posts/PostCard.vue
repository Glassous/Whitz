<script setup lang="ts">
import { computed, ref } from "vue";
import { useAuthStore } from "../../stores/auth";
import type { PostCommentItem, PostItem } from "../../types";
import MarkdownRenderer from "../chat/MarkdownRenderer.vue";
import AppIcon from "../ui/AppIcon.vue";
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
const commentsOpen = ref(false);
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
  digest: "资讯",
  insight: "观察",
  inspiration: "灵感",
  note: "动态",
};

const kindLabel = computed(() => POST_KIND_LABELS[props.post.post_kind] || "动态");

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const diffMin = Math.floor((Date.now() - d.getTime()) / 60000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin}分钟`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}小时`;
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function startReply(comment: PostCommentItem) {
  commentsOpen.value = true;
  replyTarget.value = comment;
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
      scheduledHint.value = `已发送，${assistantName.value} 稍后会来回复`;
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
  <article class="border-b border-line/65 px-4 py-3.5 transition-colors hover:bg-hover/25">
    <div class="flex items-start gap-3">
      <!-- Left Avatar Column (X-style) -->
      <div class="shrink-0 pt-0.5">
        <img
          v-if="authorAvatar"
          :src="authorAvatar"
          alt=""
          class="h-10 w-10 rounded-full bg-surface object-cover ring-1 ring-line/70"
        />
        <span
          v-else
          class="flex h-10 w-10 items-center justify-center rounded-full text-[13.5px] font-semibold ring-1 ring-line/70"
          :class="isAiPost ? 'bg-primary text-primary-fg' : 'bg-surface text-fg'"
        >
          {{ authorInitial }}
        </span>
      </div>

      <!-- Right Content Column -->
      <div class="min-w-0 flex-1">
        <!-- Compact Single-line Header -->
        <div class="flex items-center justify-between gap-2">
          <div class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[13.5px]">
            <span class="truncate font-semibold text-fg">{{ authorName }}</span>
            <span
              v-if="isAiPost"
              class="rounded bg-surface px-1.5 py-0.5 text-[11px] font-medium leading-none text-fg-muted"
            >
              {{ kindLabel }}
            </span>
            <span v-if="post.source_collection_name" class="truncate text-[12.5px] text-fg-faint">
              · {{ post.source_collection_name }}
            </span>
            <span v-else-if="!isAiPost && post.memory_entry_id" class="text-[12px] text-fg-faint">
              · 已入记忆
            </span>
            <span class="text-[12.5px] text-fg-faint">· {{ formatTime(post.created_at) }}</span>
          </div>

          <div class="flex shrink-0 items-center gap-1">
            <template v-if="confirmingDelete">
              <button
                type="button"
                class="rounded-full bg-danger px-2.5 py-0.5 text-[11.5px] font-medium text-white"
                @click="emit('delete', post.id)"
              >
                删除
              </button>
              <button
                type="button"
                class="rounded-full px-2 py-0.5 text-[11.5px] text-fg-muted hover:bg-hover"
                @click="confirmingDelete = false"
              >
                取消
              </button>
            </template>
            <button
              v-else
              type="button"
              class="focus-ring flex h-7 w-7 items-center justify-center rounded-full text-fg-faint transition-colors hover:bg-hover hover:text-danger"
              aria-label="删除动态"
              title="删除"
              @click="confirmingDelete = true"
            >
              <AppIcon name="trash" class="h-3.5 w-3.5" :stroke-width="1.85" />
            </button>
          </div>
        </div>

        <!-- Body -->
        <div class="mt-1 space-y-1">
          <p v-if="post.title" class="text-[15px] font-semibold leading-snug text-fg">
            {{ post.title }}
          </p>
          <div class="text-[14.5px] leading-[1.55] text-fg/95">
            <MarkdownRenderer :content="post.content" />
          </div>
        </div>

        <!-- Inline Hashtags -->
        <div v-if="post.tags.length > 0" class="mt-1.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[13px] text-fg-faint">
          <span v-for="tag in post.tags" :key="tag">#{{ tag }}</span>
        </div>

        <!-- X-style Compact Web Link Preview Cards -->
        <div
          v-if="post.web_sources && post.web_sources.length > 0"
          class="mt-2.5 overflow-hidden rounded-2xl border border-line/80 divide-y divide-line/60"
        >
          <a
            v-for="(src, idx) in post.web_sources.slice(0, 3)"
            :key="src.url + idx"
            :href="src.url"
            target="_blank"
            rel="noopener noreferrer"
            class="group flex items-center justify-between gap-2.5 bg-surface/40 px-3 py-2 text-[12.5px] transition-colors hover:bg-hover/60"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate font-medium text-fg group-hover:underline">{{ src.title || src.url }}</p>
              <p v-if="src.site_name" class="mt-0.5 truncate text-[11px] text-fg-faint">{{ src.site_name }}</p>
            </div>
            <AppIcon name="external-link" class="h-3.5 w-3.5 shrink-0 text-fg-faint" />
          </a>
        </div>

        <!-- AI Liked Hint -->
        <div v-if="post.ai_liked" class="mt-2 inline-flex items-center gap-1 text-[12px] text-fg-faint">
          <AppIcon name="heart" class="h-3.5 w-3.5 text-danger" :stroke-width="2" />
          <span>{{ assistantName }} 赞了</span>
        </div>

        <!-- X-style Horizontal Action Row -->
        <div class="mt-2.5 -ml-2 flex max-w-[420px] items-center justify-between text-[12.5px] text-fg-faint">
          <button
            type="button"
            class="focus-ring group inline-flex items-center gap-1 rounded-full px-2 py-1 transition-colors hover:bg-hover hover:text-fg"
            :class="commentsOpen ? 'text-fg' : ''"
            @click="commentsOpen = !commentsOpen"
          >
            <AppIcon name="message-dots" class="h-[17px] w-[17px]" :stroke-width="1.8" />
            <span v-if="post.comment_count > 0" class="tabular-nums">{{ post.comment_count }}</span>
          </button>

          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-full px-2 py-1 transition-colors hover:bg-danger-weak/80 hover:text-danger"
            :class="post.is_liked ? 'text-danger' : ''"
            @click="emit('like', post.id)"
          >
            <AppIcon name="heart" :active="post.is_liked" class="h-[17px] w-[17px]" :stroke-width="1.8" />
            <span v-if="post.is_liked">已赞</span>
          </button>

          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-full px-2 py-1 transition-colors hover:bg-warning-weak/80 hover:text-warning"
            :class="post.is_bookmarked ? 'text-warning' : ''"
            @click="emit('bookmark', post.id)"
          >
            <AppIcon name="bookmark" :active="post.is_bookmarked" class="h-[17px] w-[17px]" :stroke-width="1.8" />
          </button>

          <button
            type="button"
            class="focus-ring inline-flex items-center gap-1 rounded-full px-2 py-1 transition-colors hover:bg-hover hover:text-fg"
            title="转去聊天继续讨论"
            @click="emit('discuss', post.id)"
          >
            <AppIcon name="chat" class="h-[16px] w-[16px]" :stroke-width="1.85" />
            <span class="text-[12px]">聊聊</span>
          </button>
        </div>

        <!-- Threaded Comments -->
        <div v-if="commentsOpen" class="mt-2.5 space-y-2.5 border-l-2 border-line/80 pl-3">
          <div v-if="post.comments.length > 0" class="space-y-2">
            <div v-for="c in post.comments" :key="c.id" class="group text-[13px]">
              <div class="flex items-center justify-between gap-2">
                <div class="flex flex-wrap items-center gap-1.5">
                  <span class="font-semibold text-fg">{{ commentAuthorLabel(c.author_type) }}</span>
                  <span v-if="c.reply_to_author_type" class="text-[11.5px] text-fg-faint">
                    回复 {{ commentAuthorLabel(c.reply_to_author_type) }}
                  </span>
                  <span class="text-[11.5px] text-fg-faint">· {{ formatTime(c.created_at) }}</span>
                </div>
                <div class="flex items-center gap-2 text-[11.5px] opacity-80 group-hover:opacity-100">
                  <button type="button" class="text-fg-faint hover:text-fg" @click="startReply(c)">回复</button>
                  <button type="button" class="text-fg-faint hover:text-danger" @click="emit('delete-comment', post.id, c.id)">
                    删除
                  </button>
                </div>
              </div>
              <p v-if="c.reply_to_excerpt" class="mt-0.5 truncate text-[11.5px] text-fg-faint">
                引用：{{ c.reply_to_excerpt }}
              </p>
              <p class="mt-0.5 whitespace-pre-wrap leading-relaxed text-fg/90">{{ c.content }}</p>
              <div v-if="c.ai_liked" class="mt-0.5 inline-flex items-center gap-1 text-[11px] text-fg-faint">
                <AppIcon name="heart" class="h-3 w-3 text-danger" />
                <span>{{ assistantName }} 赞了</span>
              </div>
            </div>
          </div>

          <!-- Active reply target -->
          <div
            v-if="replyTarget"
            class="flex items-center justify-between gap-2 rounded-lg bg-surface px-2.5 py-1 text-[12px] text-fg-muted"
          >
            <span class="truncate">回复 {{ commentAuthorLabel(replyTarget.author_type) }}：{{ replyTarget.content }}</span>
            <button type="button" class="shrink-0 text-fg-faint hover:text-fg" @click="replyTarget = null">
              <AppIcon name="close" class="h-3.5 w-3.5" />
            </button>
          </div>

          <!-- Compact Comment Composer -->
          <form class="space-y-1.5" @submit.prevent="submitComment">
            <div class="flex items-center gap-2">
              <input
                v-model="commentInput"
                type="text"
                maxlength="2000"
                :placeholder="replyTarget ? `回复 ${commentAuthorLabel(replyTarget.author_type)}...` : '发布你的回复...'"
                class="focus-ring min-w-0 flex-1 rounded-full border border-line bg-canvas px-3.5 py-1.5 text-[13px] text-fg placeholder:text-fg-faint"
              />
              <BaseButton type="submit" size="sm" :disabled="!commentInput.trim() || submittingComment">
                <Spinner v-if="submittingComment" class="h-3.5 w-3.5" />
                <span v-else>回复</span>
              </BaseButton>
            </div>
            <div class="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-fg-faint">
              <label class="inline-flex cursor-pointer select-none items-center gap-1.5">
                <input v-model="triggerAiReply" type="checkbox" class="h-3.5 w-3.5 rounded accent-primary" />
                <span>邀请 {{ assistantName }} 稍后回复</span>
              </label>
              <span v-if="scheduledHint" class="text-success">{{ scheduledHint }}</span>
            </div>
          </form>
        </div>
      </div>
    </div>
  </article>
</template>
