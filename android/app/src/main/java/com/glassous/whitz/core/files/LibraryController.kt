package com.glassous.whitz.core.files

import android.net.Uri
import com.glassous.whitz.AppContainer
import com.glassous.whitz.core.model.ConversationFile
import com.glassous.whitz.core.model.LibraryContentSearchHit
import com.glassous.whitz.core.network.CompleteUploadRequest
import com.glassous.whitz.core.network.PresignRequest
import com.glassous.whitz.core.network.WhitzJson
import com.glassous.whitz.core.network.extractErrorMessage
import com.glassous.whitz.core.util.DateTimeUtils
import com.glassous.whitz.feature.chat.PreviewTarget
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

enum class LibraryUploadStatus {
    SIGNING, UPLOADING, COMPLETING, DONE, FAILED
}

data class LibraryUploadItem(
    val localId: String,
    val filename: String,
    val progress: Int = 0,
    val status: LibraryUploadStatus = LibraryUploadStatus.SIGNING,
    val error: String? = null,
)

data class LibraryUiState(
    val files: List<ConversationFile> = emptyList(),
    val totalCount: Int? = null,
    val page: Int = 1,
    val pageSize: Int = 24,
    val query: String = "",
    val searchMode: String = "filename", // "filename" | "content"
    val contentHits: List<LibraryContentSearchHit> = emptyList(),
    val contentLoading: Boolean = false,
    val category: String = "all",
    val source: String = "all",
    val loading: Boolean = false,
    val error: String? = null,
    val feedback: String? = null,
    val uploading: Boolean = false,
    val uploadItems: List<LibraryUploadItem> = emptyList(),
    val deletingId: String? = null,
    val downloadingId: String? = null,
    val reindexingIds: Set<String> = emptySet(),
    val previewTarget: PreviewTarget? = null,
)

class LibraryController(
    private val scope: CoroutineScope,
    private val container: AppContainer,
) {
    private val _ui = MutableStateFlow(LibraryUiState())
    val ui: StateFlow<LibraryUiState> = _ui.asStateFlow()

    private var loadSeq = 0
    private var searchJob: Job? = null
    private var uploadSeq = 0

    fun loadFiles() {
        val seq = ++loadSeq
        val snapshot = _ui.value
        scope.launch {
            _ui.update { it.copy(loading = true, error = null) }
            try {
                val res = container.network.api.getLibraryFiles(
                    q = snapshot.query.trim().ifBlank { null },
                    category = snapshot.category.takeIf { it != "all" },
                    source = snapshot.source.takeIf { it != "all" },
                    page = snapshot.page,
                    pageSize = snapshot.pageSize,
                )
                if (seq != loadSeq) return@launch
                var items: List<ConversationFile> = emptyList()
                var total: Int? = null
                when (res) {
                    is JsonArray -> {
                        items = res.mapNotNull { decodeFile(it) }
                    }
                    is JsonObject -> {
                        val arr = res["items"] as? JsonArray
                        items = arr?.mapNotNull { decodeFile(it) } ?: emptyList()
                        total = (res["total"] as? JsonPrimitive)?.intOrNull
                    }
                    else -> Unit
                }
                _ui.update {
                    it.copy(
                        files = items,
                        totalCount = total,
                        loading = false,
                    )
                }
            } catch (t: Throwable) {
                if (seq != loadSeq) return@launch
                _ui.update {
                    it.copy(
                        loading = false,
                        error = extractErrorMessage(t, "加载资料库失败"),
                    )
                }
            }
        }
    }

    fun setSearchMode(mode: String) {
        val clean = if (mode == "content") "content" else "filename"
        if (_ui.value.searchMode == clean) return
        searchJob?.cancel()
        _ui.update {
            it.copy(
                searchMode = clean,
                contentHits = if (clean == "filename") emptyList() else it.contentHits,
                contentLoading = false,
                error = null,
            )
        }
        val q = _ui.value.query.trim()
        if (clean == "content") {
            if (q.isNotEmpty()) runContentSearch(q)
        } else {
            _ui.update { it.copy(page = 1) }
            loadFiles()
        }
    }

    fun updateQuery(nextQuery: String) {
        _ui.update { it.copy(query = nextQuery) }
        searchJob?.cancel()
        searchJob = scope.launch {
            delay(280L)
            if (_ui.value.searchMode == "content") {
                val q = nextQuery.trim()
                if (q.isEmpty()) {
                    _ui.update { it.copy(contentHits = emptyList(), contentLoading = false) }
                } else {
                    runContentSearch(q)
                }
            } else {
                _ui.update { it.copy(page = 1) }
                loadFiles()
            }
        }
    }

    fun submitQueryNow() {
        searchJob?.cancel()
        val snapshot = _ui.value
        if (snapshot.searchMode == "content") {
            val q = snapshot.query.trim()
            if (q.isEmpty()) {
                _ui.update { it.copy(contentHits = emptyList(), contentLoading = false) }
            } else {
                runContentSearch(q)
            }
        } else {
            _ui.update { it.copy(page = 1) }
            loadFiles()
        }
    }

    private fun runContentSearch(query: String) {
        scope.launch {
            _ui.update { it.copy(contentLoading = true, error = null) }
            try {
                val resp = container.network.api.searchLibraryContent(q = query, limit = 15)
                if (_ui.value.query.trim() == query && _ui.value.searchMode == "content") {
                    _ui.update { it.copy(contentHits = resp.results, contentLoading = false) }
                }
            } catch (t: Throwable) {
                if (_ui.value.query.trim() == query) {
                    _ui.update {
                        it.copy(
                            contentLoading = false,
                            error = extractErrorMessage(t, "正文检索失败"),
                        )
                    }
                }
            }
        }
    }

    fun reindexFile(file: ConversationFile) {
        if (file.id in _ui.value.reindexingIds) return
        scope.launch {
            _ui.update {
                it.copy(
                    reindexingIds = it.reindexingIds + file.id,
                    error = null,
                    feedback = null,
                )
            }
            try {
                val updated = container.network.api.reindexLibraryFile(file.id)
                _ui.update { state ->
                    state.copy(
                        reindexingIds = state.reindexingIds - file.id,
                        files = state.files.map { f -> if (f.id == file.id) updated else f },
                        feedback = "已提交「${file.filename}」重建向量索引",
                    )
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        reindexingIds = it.reindexingIds - file.id,
                        error = extractErrorMessage(t, "重建索引失败"),
                    )
                }
            }
        }
    }

    fun openContentHitPreview(hit: LibraryContentSearchHit) {
        val existing = _ui.value.files.firstOrNull { it.id == hit.fileId }
        val file = existing ?: ConversationFile(
            id = hit.fileId,
            filename = hit.filename.ifBlank { hit.fileId },
            ext = FileValidator.getFileExt(hit.filename),
            category = FileValidator.getFileSpec(hit.filename)?.category ?: "document",
        )
        openPreview(file)
    }

    fun setCategory(nextCategory: String) {
        if (_ui.value.category == nextCategory) return
        _ui.update { it.copy(category = nextCategory, page = 1) }
        loadFiles()
    }

    fun setSource(nextSource: String) {
        if (_ui.value.source == nextSource) return
        _ui.update { it.copy(source = nextSource, page = 1) }
        loadFiles()
    }

    fun goToPage(nextPage: Int) {
        if (nextPage < 1 || nextPage == _ui.value.page) return
        _ui.update { it.copy(page = nextPage) }
        loadFiles()
    }

    fun clearFeedback() {
        _ui.update { it.copy(error = null, feedback = null) }
    }

    fun uploadUris(uris: List<Uri>) {
        if (uris.isEmpty() || _ui.value.uploading) return
        val cr = container.appContext.contentResolver
        val accepted = mutableListOf<LocalPickedFile>()
        val errors = mutableListOf<String>()
        for (uri in uris) {
            val info = UriFileReader.inspect(cr, uri)
            if (info == null) {
                errors.add("未知文件（无法读取）")
                continue
            }
            val err = FileValidator.validateFile(info.filename, info.mimeType, info.sizeBytes)
            if (err != null) {
                errors.add("${info.filename}（$err）")
            } else {
                accepted.add(info)
            }
        }

        if (accepted.isEmpty()) {
            if (errors.isNotEmpty()) {
                _ui.update { it.copy(error = errors.take(3).joinToString("；")) }
            }
            return
        }

        val items = accepted.map { f ->
            LibraryUploadItem(
                localId = "lib-up-${System.currentTimeMillis()}-${uploadSeq++}",
                filename = f.filename,
                progress = 0,
                status = LibraryUploadStatus.SIGNING,
            ) to f
        }

        scope.launch {
            _ui.update {
                it.copy(
                    uploading = true,
                    error = if (errors.isNotEmpty()) errors.take(3).joinToString("；") else null,
                    feedback = null,
                    uploadItems = items.map { pair -> pair.first },
                )
            }
            var uploadedCount = 0
            val uploadErrors = errors.toMutableList()
            val sem = Semaphore(3)
            coroutineScope {
                items.map { (item, picked) ->
                    async {
                        sem.withPermit {
                            try {
                                updateUploadItem(item.localId) {
                                    it.copy(status = LibraryUploadStatus.SIGNING, progress = 0)
                                }
                                val presign = container.network.api.presignLibraryUpload(
                                    PresignRequest(picked.filename, picked.mimeType, picked.sizeBytes)
                                )
                                updateUploadItem(item.localId) {
                                    it.copy(status = LibraryUploadStatus.UPLOADING, progress = 1)
                                }
                                val etag = container.cosUploader.putFile(
                                    presign.uploadUrl,
                                    presign.headers,
                                    picked,
                                ) { pct ->
                                    updateUploadItem(item.localId) {
                                        it.copy(status = LibraryUploadStatus.UPLOADING, progress = pct)
                                    }
                                }
                                updateUploadItem(item.localId) {
                                    it.copy(status = LibraryUploadStatus.COMPLETING, progress = 100)
                                }
                                container.network.api.completeLibraryUpload(
                                    presign.fileId,
                                    CompleteUploadRequest(etag),
                                )
                                updateUploadItem(item.localId) {
                                    it.copy(status = LibraryUploadStatus.DONE, progress = 100)
                                }
                                uploadedCount += 1
                            } catch (t: Throwable) {
                                val msg = extractErrorMessage(t, "上传失败")
                                synchronized(uploadErrors) {
                                    uploadErrors.add("${picked.filename}：$msg")
                                }
                                updateUploadItem(item.localId) {
                                    it.copy(status = LibraryUploadStatus.FAILED, progress = 0, error = msg)
                                }
                            }
                        }
                    }
                }.awaitAll()
            }

            _ui.update {
                it.copy(
                    uploading = false,
                    uploadItems = emptyList(),
                    error = if (uploadErrors.isNotEmpty()) uploadErrors.take(3).joinToString("；") else null,
                    feedback = if (uploadedCount > 0) "已上传 $uploadedCount 个文件到资料库，主聊天与旁聊均可直接参考" else null,
                    page = if (uploadedCount > 0) 1 else it.page,
                )
            }
            if (uploadedCount > 0) {
                loadFiles()
            }
        }
    }

    private fun updateUploadItem(localId: String, transform: (LibraryUploadItem) -> LibraryUploadItem) {
        _ui.update { state ->
            state.copy(uploadItems = state.uploadItems.map { if (it.localId == localId) transform(it) else it })
        }
    }

    fun deleteFile(file: ConversationFile, onDone: () -> Unit = {}) {
        if (_ui.value.deletingId != null) return
        scope.launch {
            _ui.update { it.copy(deletingId = file.id, error = null, feedback = null) }
            try {
                container.network.api.deleteLibraryFile(file.id)
                _ui.update { state ->
                    val nextTotal = state.totalCount?.let { if (it > 0) it - 1 else 0 }
                    state.copy(
                        deletingId = null,
                        files = state.files.filterNot { it.id == file.id },
                        totalCount = nextTotal,
                        feedback = "已永久删除文件「${file.filename}」，所有聊天将不再参考该文件",
                    )
                }
                onDone()
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        deletingId = null,
                        error = extractErrorMessage(t, "删除文件失败"),
                    )
                }
            }
        }
    }

    fun downloadFile(file: ConversationFile, onOpenUrl: (String) -> Unit) {
        if (_ui.value.downloadingId == file.id) return
        scope.launch {
            _ui.update { it.copy(downloadingId = file.id, error = null) }
            try {
                val url = container.network.api.getLibraryDownloadUrl(file.id, inline = false).url
                _ui.update { it.copy(downloadingId = null) }
                onOpenUrl(url)
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        downloadingId = null,
                        error = extractErrorMessage(t, "获取下载链接失败"),
                    )
                }
            }
        }
    }

    fun openPreview(file: ConversationFile) {
        _ui.update { it.copy(previewTarget = PreviewTarget(file = file, loading = true)) }
        scope.launch {
            try {
                if (file.category == "image") {
                    val expMs = DateTimeUtils.parseInstantMs(file.previewExpiresAt)
                    val url = if (!file.previewUrl.isNullOrBlank() &&
                        (expMs == 0L || System.currentTimeMillis() < expMs - 30_000L)
                    ) {
                        file.previewUrl
                    } else {
                        container.network.api.getLibraryDownloadUrl(file.id, inline = true).url
                    }
                    _ui.update {
                        it.copy(previewTarget = PreviewTarget(file = file, previewUrl = url, loading = false))
                    }
                } else {
                    val isTextLike = file.category == "code" ||
                        file.ext.lowercase() in setOf(
                            ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml"
                        )
                    if (isTextLike) {
                        val body = container.network.api.getLibraryPreviewContent(file.id).string()
                        var text = body
                        var truncated = false
                        try {
                            val elem = WhitzJson.parseToJsonElement(body)
                            if (elem is JsonObject) {
                                text = (elem["content"] as? JsonPrimitive)?.contentOrNull
                                    ?: (elem["text"] as? JsonPrimitive)?.contentOrNull
                                    ?: body
                                truncated = (elem["truncated"] as? JsonPrimitive)?.booleanOrNull ?: false
                            }
                        } catch (_: Exception) {
                            /* plain text */
                        }
                        _ui.update {
                            it.copy(
                                previewTarget = PreviewTarget(
                                    file = file,
                                    content = text,
                                    truncated = truncated,
                                    loading = false,
                                )
                            )
                        }
                    } else {
                        val url = container.network.api.getLibraryDownloadUrl(file.id, inline = false).url
                        _ui.update {
                            it.copy(previewTarget = PreviewTarget(file = file, previewUrl = url, loading = false))
                        }
                    }
                }
            } catch (t: Throwable) {
                _ui.update {
                    it.copy(
                        previewTarget = PreviewTarget(
                            file = file,
                            loading = false,
                            error = extractErrorMessage(t, "预览加载失败"),
                        )
                    )
                }
            }
        }
    }

    fun closePreview() {
        _ui.update { it.copy(previewTarget = null) }
    }

    fun handleRealtimeLibraryEvent(action: String, fileId: String?, indexStatus: String?, indexedChunks: Int?) {
        when (action) {
            "deleted" -> if (fileId != null) {
                _ui.update { state ->
                    state.copy(files = state.files.filterNot { it.id == fileId })
                }
            }
            "indexed" -> if (fileId != null) {
                _ui.update { state ->
                    state.copy(
                        files = state.files.map { f ->
                            if (f.id == fileId) {
                                f.copy(
                                    indexStatus = indexStatus ?: "ready",
                                    indexedChunks = indexedChunks ?: f.indexedChunks,
                                )
                            } else f
                        }
                    )
                }
            }
        }
        val st = _ui.value
        if (!st.uploading && st.deletingId == null && st.files.isNotEmpty()) {
            loadFiles()
        }
    }

    private fun decodeFile(elem: kotlinx.serialization.json.JsonElement): ConversationFile? {
        return try {
            WhitzJson.decodeFromJsonElement(ConversationFile.serializer(), elem)
        } catch (_: Exception) {
            null
        }
    }
}
