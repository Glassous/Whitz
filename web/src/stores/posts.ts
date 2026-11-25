import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api/client";
import type {
  PostCommentCreateResponse,
  PostCommentItem,
  PostDiscussResponse,
  PostItem,
  PostListResponse,
  PostQuotaSummary,
  User,
} from "../types";
import { useAuthStore } from "./auth";

export type PostFeedFilter = "all" | "ai" | "user" | "bookmarked";

export const usePostsStore = defineStore("posts", () => {
  const items = ref<PostItem[]>([]);
  const quota = ref<PostQuotaSummary | null>(null);
  const nextCursor = ref<string | null>(null);
  const loading = ref(false);
  const loadingMore = ref(false);
  const filter = ref<PostFeedFilter>("all");
  const selectedCollectionId = ref<string | null>(null);
  const hasUnread = ref(false);
  const error = ref<string | null>(null);

  function buildQuery(cursor?: string | null): string {
    const params = new URLSearchParams();
    if (filter.value === "ai" || filter.value === "user") {
      params.set("author_type", filter.value);
    } else if (filter.value === "bookmarked") {
      params.set("bookmarked_only", "true");
    }
    if (selectedCollectionId.value) {
      params.set("collection_id", selectedCollectionId.value);
    }
    if (cursor) {
      params.set("cursor", cursor);
    }
    params.set("limit", "20");
    return `/posts?${params.toString()}`;
  }

  async function fetchQuota() {
    try {
      quota.value = await api.get<PostQuotaSummary>("/posts/quota");
    } catch {
      /* ignore quota prefetch errors */
    }
  }

  async function fetchFeed(reset = true) {
    if (reset) {
      loading.value = true;
    } else {
      loadingMore.value = true;
    }
    error.value = null;
    try {
      const res = await api.get<PostListResponse>(buildQuery(reset ? null : nextCursor.value));
      quota.value = res.quota;
      nextCursor.value = res.next_cursor;
      if (reset) {
        items.value = res.items;
      } else {
        const seen = new Set(items.value.map((p) => p.id));
        const extra = res.items.filter((p) => !seen.has(p.id));
        items.value = [...items.value, ...extra];
      }
    } catch (e: any) {
      error.value = e?.detail?.detail || e?.message || "加载动态失败";
    } finally {
      loading.value = false;
      loadingMore.value = false;
    }
  }

  async function setFilter(next: PostFeedFilter) {
    if (filter.value === next) return;
    filter.value = next;
    await fetchFeed(true);
  }

  async function setCollectionFilter(collectionId: string | null) {
    if (selectedCollectionId.value === collectionId) return;
    selectedCollectionId.value = collectionId;
    await fetchFeed(true);
  }

  async function setAiPostsEnabled(enabled: boolean): Promise<User> {
    const auth = useAuthStore();
    const updated = await api.put<User>("/users/me/ai-posts", {
      ai_posts_enabled: enabled,
    });
    auth.user = updated;
    if (quota.value) {
      quota.value = {
        ...quota.value,
        ai_posts_enabled: Boolean(updated.ai_posts_enabled),
        ai_posts_consented_at: updated.ai_posts_consented_at ?? null,
      };
    }
    if (enabled) {
      await fetchFeed(true);
    }
    return updated;
  }

  async function createUserPost(payload: { title?: string; content: string; tags?: string[] }): Promise<PostItem> {
    const created = await api.post<PostItem>("/posts", {
      title: payload.title || "",
      content: payload.content,
      tags: payload.tags || [],
    });
    if (filter.value === "all" || filter.value === "user") {
      items.value = [created, ...items.value.filter((p) => p.id !== created.id)];
    }
    void fetchQuota();
    return created;
  }

  async function deletePost(postId: string) {
    await api.delete(`/posts/${postId}`);
    items.value = items.value.filter((p) => p.id !== postId);
  }

  async function toggleLike(postId: string) {
    const updated = await api.post<PostItem>(`/posts/${postId}/like`);
    replacePost(updated);
  }

  async function toggleBookmark(postId: string) {
    const updated = await api.post<PostItem>(`/posts/${postId}/bookmark`);
    if (filter.value === "bookmarked" && !updated.is_bookmarked) {
      items.value = items.value.filter((p) => p.id !== postId);
    } else {
      replacePost(updated);
    }
  }

  async function addComment(
    postId: string,
    payload: { content: string; reply_to_id?: string | null; trigger_ai_reply?: boolean },
  ): Promise<PostCommentCreateResponse> {
    const res = await api.post<PostCommentCreateResponse>(`/posts/${postId}/comments`, {
      content: payload.content,
      reply_to_id: payload.reply_to_id ?? null,
      trigger_ai_reply: payload.trigger_ai_reply ?? true,
    });
    appendComment(postId, res.comment);
    return res;
  }

  async function deleteComment(postId: string, commentId: string) {
    await api.delete(`/posts/${postId}/comments/${commentId}`);
    const target = items.value.find((p) => p.id === postId);
    if (target) {
      target.comments = target.comments.filter((c) => c.id !== commentId);
      target.comment_count = target.comments.length;
    }
  }

  async function discussInChat(postId: string): Promise<PostDiscussResponse> {
    const res = await api.post<PostDiscussResponse>(`/posts/${postId}/discuss`);
    const target = items.value.find((p) => p.id === postId);
    if (target) {
      target.conversation_id = res.conversation_id;
    }
    return res;
  }

  function replacePost(updated: PostItem) {
    const idx = items.value.findIndex((p) => p.id === updated.id);
    if (idx >= 0) {
      const next = [...items.value];
      next[idx] = updated;
      items.value = next;
    }
  }

  function appendComment(postId: string, comment: PostCommentItem, likedCommentId?: string | null) {
    const target = items.value.find((p) => p.id === postId);
    if (!target) return;
    if (likedCommentId) {
      const liked = target.comments.find((c) => c.id === likedCommentId);
      if (liked) liked.ai_liked = true;
    }
    if (!target.comments.some((c) => c.id === comment.id)) {
      target.comments = [...target.comments, comment];
      target.comment_count = target.comments.length;
    }
  }

  function applyRealtimeUpdate(data: Record<string, any>) {
    const postId = typeof data.post_id === "string" ? data.post_id : null;
    if (!postId) return;
    const target = items.value.find((p) => p.id === postId);
    if (!target) return;
    if (typeof data.ai_liked === "boolean") {
      target.ai_liked = data.ai_liked;
    }
    if (typeof data.liked_comment_id === "string") {
      const c = target.comments.find((x) => x.id === data.liked_comment_id);
      if (c) c.ai_liked = true;
    }
  }

  function markRead() {
    hasUnread.value = false;
  }

  return {
    items,
    quota,
    nextCursor,
    loading,
    loadingMore,
    filter,
    selectedCollectionId,
    hasUnread,
    error,
    fetchQuota,
    fetchFeed,
    setFilter,
    setCollectionFilter,
    setAiPostsEnabled,
    createUserPost,
    deletePost,
    toggleLike,
    toggleBookmark,
    addComment,
    deleteComment,
    discussInChat,
    appendComment,
    applyRealtimeUpdate,
    markRead,
  };
});
