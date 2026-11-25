package com.glassous.whitz.feature.posts

import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.model.PostCommentItem
import com.glassous.whitz.core.model.PostDiscussResponse
import com.glassous.whitz.core.model.PostItem
import com.glassous.whitz.core.model.PostQuotaSummary
import com.glassous.whitz.core.network.PostCommentCreateRequest
import com.glassous.whitz.core.network.PostCreateRequest
import com.glassous.whitz.core.network.UpdateAiPostsRequest
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.network.extractErrorMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

enum class PostFeedFilter(val label: String) {
    ALL("全部"),
    AI("AI 动态"),
    USER("我的动态"),
    BOOKMARKED("已收藏"),
}

data class PostsUiState(
    val items: List<PostItem> = emptyList(),
    val quota: PostQuotaSummary? = null,
    val nextCursor: String? = null,
    val filter: PostFeedFilter = PostFeedFilter.ALL,
    val loading: Boolean = false,
    val loadingMore: Boolean = false,
    val togglingEnable: Boolean = false,
    val publishing: Boolean = false,
    val hasUnread: Boolean = false,
    val error: String? = null,
    val feedback: String? = null,
)

class PostsController(
    private val scope: CoroutineScope,
    private val container: AppContainer,
) {
    private val _ui = MutableStateFlow(PostsUiState())
    val ui: StateFlow<PostsUiState> = _ui.asStateFlow()

    fun clearMessages() {
        _ui.update { it.copy(error = null, feedback = null) }
    }

    fun markRead() {
        if (_ui.value.hasUnread) {
            _ui.update { it.copy(hasUnread = false) }
        }
    }

    fun loadQuota() {
        scope.launch {
            try {
                val quota = container.network.api.getPostQuota()
                _ui.update { it.copy(quota = quota) }
            } catch (_: Throwable) {
                /* ignore prefetch errors */
            }
        }
    }

    fun loadFeed(reset: Boolean = true, silent: Boolean = false) {
        val state = _ui.value
        val cursor = if (reset) null else state.nextCursor
        if (!reset && (cursor.isNullOrBlank() || state.loadingMore)) return

        scope.launch {
            _ui.update {
                if (reset) {
                    it.copy(loading = !silent, error = null)
                } else {
                    it.copy(loadingMore = true, error = null)
                }
            }
            try {
                val filter = _ui.value.filter
                val res = container.network.api.getPosts(
                    authorType = when (filter) {
                        PostFeedFilter.AI -> "ai"
                        PostFeedFilter.USER -> "user"
                        else -> null
                    },
                    bookmarkedOnly = filter == PostFeedFilter.BOOKMARKED,
                    cursor = cursor,
                    limit = 20,
                )
                _ui.update { cur ->
                    val merged = if (reset) {
                        res.items
                    } else {
                        val seen = cur.items.mapTo(HashSet()) { it.id }
                        cur.items + res.items.filterNot { it.id in seen }
                    }
                    cur.copy(
                        items = merged,
                        quota = res.quota,
                        nextCursor = res.nextCursor,
                        loading = false,
                        loadingMore = false,
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        loading = false,
                        loadingMore = false,
                        error = extractErrorMessage(t, "加载动态失败"),
                    )
                }
            }
        }
    }

    fun setFilter(next: PostFeedFilter) {
        if (_ui.value.filter == next) return
        _ui.update { it.copy(filter = next) }
        loadFeed(reset = true)
    }

    fun setAiPostsEnabled(enabled: Boolean) {
        if (_ui.value.togglingEnable) return
        scope.launch {
            _ui.update { it.copy(togglingEnable = true, error = null, feedback = null) }
            try {
                val updatedUser = container.network.api.updateAiPosts(UpdateAiPostsRequest(enabled))
                container.authManager.updateUser(updatedUser)
                _ui.update { cur ->
                    cur.copy(
                        togglingEnable = false,
                        quota = cur.quota?.copy(
                            aiPostsEnabled = updatedUser.aiPostsEnabled,
                            aiPostsConsentedAt = updatedUser.aiPostsConsentedAt,
                        ),
                        feedback = if (enabled) "已开启私人动态（正常消耗积分额度）" else "已关闭 AI 每日联网动态",
                    )
                }
                if (enabled) {
                    loadFeed(reset = true)
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        togglingEnable = false,
                        error = extractErrorMessage(t, "更新设置失败"),
                    )
                }
            }
        }
    }

    fun createUserPost(
        title: String,
        content: String,
        tags: List<String>,
        onSuccess: (PostItem) -> Unit = {},
    ) {
        val cleaned = content.trim()
        if (cleaned.isEmpty() || _ui.value.publishing) return
        scope.launch {
            _ui.update { it.copy(publishing = true, error = null, feedback = null) }
            try {
                val created = container.network.api.createPost(
                    PostCreateRequest(
                        title = title.trim(),
                        content = cleaned,
                        tags = tags,
                    ),
                )
                _ui.update { cur ->
                    val shouldPrepend = cur.filter == PostFeedFilter.ALL || cur.filter == PostFeedFilter.USER
                    val nextItems = if (shouldPrepend) {
                        listOf(created) + cur.items.filterNot { it.id == created.id }
                    } else {
                        cur.items
                    }
                    cur.copy(
                        items = nextItems,
                        publishing = false,
                        feedback = if (created.memoryEntryId != null) {
                            "已发布并同步至长期记忆，助手稍后会来互动"
                        } else {
                            "已发布，助手稍后会来互动"
                        },
                    )
                }
                loadQuota()
                onSuccess(created)
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        publishing = false,
                        error = extractErrorMessage(t, "发布动态失败"),
                    )
                }
            }
        }
    }

    fun toggleLike(postId: String) {
        scope.launch {
            try {
                val updated = container.network.api.togglePostLike(postId)
                replacePost(updated)
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "点赞失败")) }
            }
        }
    }

    fun toggleBookmark(postId: String) {
        scope.launch {
            try {
                val updated = container.network.api.togglePostBookmark(postId)
                _ui.update { cur ->
                    if (cur.filter == PostFeedFilter.BOOKMARKED && !updated.isBookmarked) {
                        cur.copy(items = cur.items.filterNot { it.id == postId })
                    } else {
                        cur.copy(items = cur.items.map { if (it.id == updated.id) updated else it })
                    }
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "收藏操作失败")) }
            }
        }
    }

    fun deletePost(postId: String) {
        scope.launch {
            try {
                container.network.api.deletePost(postId)
                _ui.update { cur ->
                    cur.copy(
                        items = cur.items.filterNot { it.id == postId },
                        feedback = "动态已删除",
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除动态失败")) }
            }
        }
    }

    fun addComment(
        postId: String,
        content: String,
        replyToId: String? = null,
        triggerAiReply: Boolean = true,
        onSuccess: (Boolean) -> Unit = {},
    ) {
        val cleaned = content.trim()
        if (cleaned.isEmpty()) return
        scope.launch {
            try {
                val res = container.network.api.createPostComment(
                    postId,
                    PostCommentCreateRequest(
                        content = cleaned,
                        replyToId = replyToId,
                        triggerAiReply = triggerAiReply,
                    ),
                )
                appendComment(postId, res.comment, null)
                if (res.aiReplyScheduled) {
                    _ui.update { it.copy(feedback = "评论已发送，助手稍后会来看并回复") }
                }
                onSuccess(res.aiReplyScheduled)
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "发送评论失败")) }
            }
        }
    }

    fun deleteComment(postId: String, commentId: String) {
        scope.launch {
            try {
                container.network.api.deletePostComment(postId, commentId)
                _ui.update { cur ->
                    cur.copy(
                        items = cur.items.map { p ->
                            if (p.id != postId) p
                            else {
                                val nextComments = p.comments.filterNot { it.id == commentId }
                                p.copy(comments = nextComments, commentCount = nextComments.size)
                            }
                        },
                    )
                }
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "删除评论失败")) }
            }
        }
    }

    fun discussInChat(
        postId: String,
        onReady: (PostDiscussResponse) -> Unit,
    ) {
        scope.launch {
            try {
                val res = container.network.api.discussPostInChat(postId)
                _ui.update { cur ->
                    cur.copy(
                        items = cur.items.map { p ->
                            if (p.id == postId) p.copy(conversationId = res.conversationId) else p
                        },
                    )
                }
                onReady(res)
            } catch (t: Throwable) {
                _ui.update { it.copy(error = extractErrorMessage(t, "转去聊天失败")) }
            }
        }
    }

    fun handleRealtimeEvent(event: String, data: JsonObject) {
        when (event) {
            "post.created" -> {
                _ui.update { it.copy(hasUnread = true) }
                loadFeed(reset = true, silent = true)
            }
            "post.updated" -> {
                val postId = data["post_id"]?.jsonPrimitive?.contentOrNull ?: return
                val aiLiked = data["ai_liked"]?.jsonPrimitive?.booleanOrNull
                val likedCommentId = data["liked_comment_id"]?.jsonPrimitive?.contentOrNull
                _ui.update { cur ->
                    cur.copy(
                        hasUnread = true,
                        items = cur.items.map { p ->
                            if (p.id != postId) p
                            else p.copy(
                                aiLiked = aiLiked ?: p.aiLiked,
                                comments = if (likedCommentId != null) {
                                    p.comments.map { c -> if (c.id == likedCommentId) c.copy(aiLiked = true) else c }
                                } else {
                                    p.comments
                                },
                            )
                        },
                    )
                }
            }
            "post.comment_created" -> {
                val postId = data["post_id"]?.jsonPrimitive?.contentOrNull ?: return
                val likedCommentId = data["liked_comment_id"]?.jsonPrimitive?.contentOrNull
                val commentElem = data["comment"] ?: return
                val comment = runCatching {
                    WhitzJson.decodeFromJsonElement(PostCommentItem.serializer(), commentElem)
                }.getOrNull() ?: return
                appendComment(postId, comment, likedCommentId)
                if (comment.authorType == "ai") {
                    _ui.update { it.copy(hasUnread = true) }
                }
            }
        }
    }

    private fun replacePost(updated: PostItem) {
        _ui.update { cur ->
            cur.copy(items = cur.items.map { if (it.id == updated.id) updated else it })
        }
    }

    private fun appendComment(postId: String, comment: PostCommentItem, likedCommentId: String?) {
        _ui.update { cur ->
            cur.copy(
                items = cur.items.map { p ->
                    if (p.id != postId) p
                    else {
                        val updatedExisting = if (likedCommentId != null) {
                            p.comments.map { c -> if (c.id == likedCommentId) c.copy(aiLiked = true) else c }
                        } else {
                            p.comments
                        }
                        val nextComments = if (updatedExisting.any { it.id == comment.id }) {
                            updatedExisting
                        } else {
                            updatedExisting + comment
                        }
                        p.copy(comments = nextComments, commentCount = nextComments.size)
                    }
                },
            )
        }
    }
}
