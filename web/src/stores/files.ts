import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";
import {
  MAX_FILES_PER_CONVERSATION,
  SUPPORTED_TYPES_SUMMARY,
  getFileExt,
  getFileSpec,
  validateSelectedFiles,
} from "../lib/fileTypes";
import type { ConversationFile, LibraryFileItem, UploadTask } from "../types";

export interface PreviewContentResult {
  content: string;
  truncated?: boolean;
  mime_type?: string;
  filename?: string;
  ext?: string;
}

interface PresignResponse {
  file_id: string;
  filename: string;
  ext: string;
  category: string;
  mime_type: string;
  size_bytes: number;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  expires_in: number;
}

function errorText(e: any, fallback: string): string {
  const detail = e?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.detail === "string") return detail.detail;
  return e?.message ?? fallback;
}

function putToCos(
  url: string,
  headers: Record<string, string>,
  file: File,
  onProgress: (pct: number) => void,
  onRegisterAbort: (abort: () => void) => void,
): Promise<{ etag: string | null }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url, true);
    for (const [k, v] of Object.entries(headers)) {
      xhr.setRequestHeader(k, v);
    }
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && ev.total > 0) {
        onProgress(Math.min(99, Math.round((ev.loaded / ev.total) * 100)));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const etag = xhr.getResponseHeader("ETag")?.replaceAll('"', "") ?? null;
        onProgress(100);
        resolve({ etag });
      } else {
        reject(new Error(`直传 COS 失败（HTTP ${xhr.status}）`));
      }
    };
    xhr.onerror = () => reject(new Error("网络异常或 COS 跨域配置拒绝了上传请求"));
    xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
    onRegisterAbort(() => xhr.abort());
    xhr.send(file);
  });
}

let uploadSeq = 0;

export interface EnqueueFilesOptions {
  attachToBar?: boolean;
  onTaskCreated?: (task: UploadTask) => void;
  onTaskCompleted?: (localId: string, file: ConversationFile) => void;
  onTaskFailed?: (localId: string, err: string) => void;
}

export const useFilesStore = defineStore("files", () => {
  const convId = ref<string | null>(null);
  const listScope = ref<"conversation" | "all">("conversation");
  const files = ref<ConversationFile[]>([]);
  const uploads = ref<UploadTask[]>([]);
  const attachedIds = ref<string[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const abortMap = new Map<string, () => void>();
  let listRefreshPromise: { cid: string; promise: Promise<ConversationFile[]> } | null = null;

  const activeUploads = computed(() =>
    uploads.value.filter((u) => u.status === "signing" || u.status === "uploading" || u.status === "completing"),
  );
  const hasActiveUploads = computed(() => activeUploads.value.length > 0);
  const fileCount = computed(() => files.value.length);
  const attachedFiles = computed(() => {
    const idSet = new Set(attachedIds.value);
    return files.value.filter((f) => idSet.has(f.id));
  });

  function revokeTaskPreview(task?: UploadTask) {
    if (task?.localPreviewUrl) {
      URL.revokeObjectURL(task.localPreviewUrl);
      task.localPreviewUrl = null;
    }
  }

  function revokeAllPreviews() {
    for (const u of uploads.value) {
      revokeTaskPreview(u);
    }
  }

  function clearError() {
    error.value = null;
  }

  function reset() {
    for (const abort of abortMap.values()) {
      abort();
    }
    abortMap.clear();
    listRefreshPromise = null;
    revokeAllPreviews();
    convId.value = null;
    files.value = [];
    uploads.value = [];
    attachedIds.value = [];
    loading.value = false;
    error.value = null;
  }

  async function load(conversationId: string, scope: "conversation" | "all" = "conversation") {
    if (convId.value !== conversationId) {
      for (const abort of abortMap.values()) abort();
      abortMap.clear();
      listRefreshPromise = null;
      revokeAllPreviews();
      uploads.value = [];
      attachedIds.value = [];
      error.value = null;
    }
    convId.value = conversationId;
    listScope.value = scope;
    loading.value = true;
    try {
      const qs = scope === "all" ? "?scope=all" : "";
      files.value = await api.get<ConversationFile[]>(`/conversations/${conversationId}/files${qs}`);
    } catch (e: any) {
      error.value = errorText(e, "加载对话文件失败");
      files.value = [];
    } finally {
      loading.value = false;
    }
  }

  function setRejectionMessage(rejected: { filename: string; reason: string }[]) {
    if (!rejected.length) return;
    const head = rejected
      .slice(0, 3)
      .map((r) => `${r.filename}（${r.reason}）`)
      .join("；");
    const extra = rejected.length > 3 ? ` 等 ${rejected.length} 个文件` : "";
    error.value = `部分文件无法上传：${head}${extra}。${SUPPORTED_TYPES_SUMMARY}`;
  }

  async function runUploadTask(
    targetConvId: string,
    taskId: string,
    file: File,
    options?: EnqueueFilesOptions,
  ) {
    const findTask = () => uploads.value.find((u) => u.localId === taskId);
    try {
      const presign = await api.post<PresignResponse>(`/conversations/${targetConvId}/files/presign`, {
        filename: file.name,
        mime_type: file.type || "",
        size_bytes: file.size,
      });

      const t1 = findTask();
      if (!t1) return;
      t1.status = "uploading";
      t1.progress = 1;

      const { etag } = await putToCos(
        presign.upload_url,
        presign.headers,
        file,
        (pct) => {
          const cur = findTask();
          if (cur) cur.progress = pct;
        },
        (abortFn) => abortMap.set(taskId, abortFn),
      );
      abortMap.delete(taskId);

      const t2 = findTask();
      if (!t2) return;
      t2.status = "completing";
      t2.progress = 100;

      const completed = await api.post<ConversationFile>(
        `/conversations/${targetConvId}/files/${presign.file_id}/complete`,
        { etag },
      );

      if (convId.value === targetConvId || listScope.value === "all") {
        files.value = [completed, ...files.value.filter((f) => f.id !== completed.id)];
        if (options?.attachToBar !== false && !attachedIds.value.includes(completed.id)) {
          attachedIds.value = [...attachedIds.value, completed.id];
        }
      }
      options?.onTaskCompleted?.(taskId, completed);
      revokeTaskPreview(findTask());
      uploads.value = uploads.value.filter((u) => u.localId !== taskId);
    } catch (e: any) {
      abortMap.delete(taskId);
      if (e?.name === "AbortError") {
        revokeTaskPreview(findTask());
        uploads.value = uploads.value.filter((u) => u.localId !== taskId);
        return;
      }
      const msg = errorText(e, "上传失败");
      const cur = findTask();
      if (cur) {
        cur.status = "error";
        cur.error = msg;
      }
      error.value = errorText(e, `${file.name} 上传失败`);
      options?.onTaskFailed?.(taskId, msg);
    }
  }

  async function enqueueFiles(
    inputFiles: FileList | File[],
    ensureConversation: () => Promise<string>,
    dataTransfer?: DataTransfer | null,
    options?: EnqueueFilesOptions,
  ): Promise<boolean> {
    error.value = null;
    const { accepted, rejected } = validateSelectedFiles(inputFiles, dataTransfer);
    setRejectionMessage(rejected);
    if (!accepted.length) return false;

    const currentUsed = files.value.length + activeUploads.value.length;
    const remainingSlots =
      listScope.value === "all"
        ? accepted.length
        : Math.max(0, MAX_FILES_PER_CONVERSATION - currentUsed);
    if (remainingSlots <= 0) {
      error.value = `当前对话最多保留 ${MAX_FILES_PER_CONVERSATION} 个文件，请先删除部分文件后再上传`;
      return false;
    }

    const queue = accepted.slice(0, remainingSlots);
    if (accepted.length > remainingSlots) {
      error.value = `超出单对话 ${MAX_FILES_PER_CONVERSATION} 个文件上限，仅保留前 ${remainingSlots} 个文件`;
    }

    // Immediately push optimistic upload chips BEFORE awaiting ensureConversation() so
    // the Send button locks & displays upload progress instantly even on a brand-new draft!
    const createdTasks: { taskId: string; file: File }[] = [];
    for (const file of queue) {
      const taskId = `up-${Date.now()}-${uploadSeq++}`;
      const spec = getFileSpec(file.name);
      const isImage = spec?.category === "image" || file.type.startsWith("image/");
      const localPreviewUrl =
        isImage && typeof URL !== "undefined" && typeof URL.createObjectURL === "function"
          ? URL.createObjectURL(file)
          : null;
      const taskObj: UploadTask = {
        localId: taskId,
        filename: file.name,
        ext: spec?.ext ?? getFileExt(file.name),
        category: spec?.category ?? "document",
        sizeBytes: file.size,
        progress: 0,
        status: "signing",
        file,
        localPreviewUrl,
      };
      uploads.value = [...uploads.value, taskObj];
      options?.onTaskCreated?.(taskObj);
      createdTasks.push({ taskId, file });
    }

    let targetConvId: string;
    try {
      targetConvId = await ensureConversation();
      convId.value = targetConvId;
    } catch (e: any) {
      error.value = errorText(e, "无法创建对话以保存文件");
      for (const t of createdTasks) {
        updateTask(t.taskId, { status: "error", error: "创建对话失败" });
        options?.onTaskFailed?.(t.taskId, "创建对话失败");
      }
      return false;
    }

    // 限制并发直传数（最多 3 个并发）
    const concurrency = 3;
    let idx = 0;
    const workers = Array.from({ length: Math.min(concurrency, createdTasks.length) }, async () => {
      while (idx < createdTasks.length) {
        const next = createdTasks[idx++];
        if (!next) break;
        await runUploadTask(targetConvId, next.taskId, next.file, options);
      }
    });
    await Promise.all(workers);
    return true;
  }

  function updateTask(localId: string, patch: Partial<UploadTask>) {
    const idx = uploads.value.findIndex((u) => u.localId === localId);
    if (idx < 0) return;
    const next = [...uploads.value];
    next[idx] = { ...next[idx], ...patch };
    uploads.value = next;
  }

  async function retryUpload(
    localId: string,
    ensureConversation?: () => Promise<string>,
  ): Promise<boolean> {
    const task = uploads.value.find((u) => u.localId === localId);
    if (!task || !task.file) return false;
    let targetConvId = convId.value;
    if (!targetConvId && ensureConversation) {
      try {
        targetConvId = await ensureConversation();
        convId.value = targetConvId;
      } catch (e: any) {
        updateTask(localId, { status: "error", error: errorText(e, "创建对话失败") });
        return false;
      }
    }
    if (!targetConvId) return false;
    updateTask(localId, { status: "signing", progress: 0, error: undefined });
    await runUploadTask(targetConvId, localId, task.file);
    return true;
  }

  function cancelUpload(localId: string) {
    const abort = abortMap.get(localId);
    if (abort) {
      abort();
      abortMap.delete(localId);
    }
    const task = uploads.value.find((u) => u.localId === localId);
    revokeTaskPreview(task);
    uploads.value = uploads.value.filter((u) => u.localId !== localId);
  }

  function dismissUpload(localId: string) {
    const task = uploads.value.find((u) => u.localId === localId);
    revokeTaskPreview(task);
    uploads.value = uploads.value.filter((u) => u.localId !== localId);
  }

  function detachFile(fileId: string) {
    attachedIds.value = attachedIds.value.filter((id) => id !== fileId);
  }

  function consumeAttachedIds(): string[] {
    const ids = [...attachedIds.value];
    attachedIds.value = [];
    return ids;
  }

  function upsertFile(file: ConversationFile) {
    if (
      listScope.value !== "all" &&
      convId.value &&
      file.conversation_id &&
      file.conversation_id !== convId.value
    ) {
      return;
    }
    const idx = files.value.findIndex((f) => f.id === file.id);
    if (idx >= 0) {
      const next = [...files.value];
      next[idx] = { ...next[idx], ...file };
      files.value = next;
    } else {
      files.value = [file, ...files.value];
    }
  }

  async function createTextFile(
    filename: string,
    content: string,
    ensureConversation: () => Promise<string>,
    overwrite = false,
  ): Promise<ConversationFile> {
    const cid = convId.value ?? (await ensureConversation());
    convId.value = cid;
    const created = await api.post<ConversationFile>(`/conversations/${cid}/files/text`, {
      filename,
      content,
      overwrite,
    });
    upsertFile(created);
    return created;
  }

  async function updateFileContent(
    fileId: string,
    content: string,
    targetConvId?: string | null,
  ): Promise<ConversationFile> {
    const cid = targetConvId || convId.value;
    if (!cid) throw new Error("未选择对话");
    const updated = await api.put<ConversationFile>(
      `/conversations/${cid}/files/${fileId}/content`,
      { content },
    );
    upsertFile(updated);
    return updated;
  }

  async function renameFile(
    fileId: string,
    filename: string,
    targetConvId?: string | null,
  ): Promise<ConversationFile> {
    const cid = targetConvId || convId.value;
    if (!cid) throw new Error("未选择对话");
    const updated = await api.patch<ConversationFile>(
      `/conversations/${cid}/files/${fileId}`,
      { filename },
    );
    upsertFile(updated);
    return updated;
  }

  async function removeFile(fileId: string) {
    if (!convId.value) return;
    await api.delete(`/conversations/${convId.value}/files/${fileId}`);
    removeLocalFile(fileId);
  }

  function removeLocalFile(fileId: string) {
    files.value = files.value.filter((f) => f.id !== fileId);
    attachedIds.value = attachedIds.value.filter((id) => id !== fileId);
  }

  function patchLocalIndexStatus(fileId: string, indexStatus: string, indexedChunks?: number) {
    const idx = files.value.findIndex((f) => f.id === fileId);
    if (idx < 0) return;
    const next = [...files.value];
    next[idx] = {
      ...next[idx],
      index_status: indexStatus,
      ...(typeof indexedChunks === "number" ? { indexed_chunks: indexedChunks } : {}),
    };
    files.value = next;
  }

  async function getDownloadUrl(fileId: string, inline = false, targetConvId?: string): Promise<string | null> {
    const cid = targetConvId ?? convId.value;
    if (!cid) return null;
    const res = await api.get<{ url: string; expires_in: number }>(
      `/conversations/${cid}/files/${fileId}/download-url?inline=${inline ? "true" : "false"}`,
    );
    return res.url;
  }

  function isPreviewUrlExpiring(file: ConversationFile, bufferMs = 30_000): boolean {
    if (!file.preview_url) return true;
    if (!file.preview_expires_at) return false;
    const expMs = Date.parse(file.preview_expires_at);
    if (Number.isNaN(expMs)) return false;
    return Date.now() >= expMs - bufferMs;
  }

  async function ensureFreshUrl(file: ConversationFile, force = false): Promise<string | null> {
    const existing = files.value.find((f) => f.id === file.id) ?? file;
    const isImage = existing.category === "image" || getFileSpec(existing.filename)?.category === "image";
    if (!force && existing.preview_url && !isPreviewUrlExpiring(existing)) {
      return existing.preview_url;
    }
    const cid = existing.conversation_id ?? convId.value;
    if (!cid) return existing.preview_url ?? null;

    if (isImage && convId.value === cid) {
      try {
        if (!listRefreshPromise || listRefreshPromise.cid !== cid) {
          const promise = api.get<ConversationFile[]>(`/conversations/${cid}/files`).finally(() => {
            if (listRefreshPromise?.cid === cid && listRefreshPromise.promise === promise) {
              listRefreshPromise = null;
            }
          });
          listRefreshPromise = { cid, promise };
        }
        const refreshedList = await listRefreshPromise.promise;
        if (convId.value === cid) {
          const byId = new Map(refreshedList.map((item) => [item.id, item]));
          const existingIds = new Set(files.value.map((f) => f.id));
          const merged = files.value.map((f) => {
            const freshItem = byId.get(f.id);
            return freshItem ? { ...f, ...freshItem } : f;
          });
          for (const item of refreshedList) {
            if (!existingIds.has(item.id)) {
              merged.push(item);
            }
          }
          files.value = merged;
          const refreshed = byId.get(existing.id);
          if (refreshed?.preview_url) {
            return refreshed.preview_url;
          }
        }
      } catch {
        /* fallback to single-file download-url below */
      }
    }

    const res = await api.get<{ url: string; expires_in: number }>(
      `/conversations/${cid}/files/${existing.id}/download-url?inline=true`,
    );
    const expiresAt = new Date(Date.now() + (res.expires_in || 300) * 1000).toISOString();
    const freshThumb = isImage ? res.url : null;
    const idx = files.value.findIndex((f) => f.id === existing.id);
    if (idx >= 0) {
      const next = [...files.value];
      next[idx] = {
        ...next[idx],
        preview_url: res.url,
        thumb_url: freshThumb,
        preview_expires_at: expiresAt,
      };
      files.value = next;
    } else if (convId.value === cid) {
      upsertFile({
        ...existing,
        preview_url: res.url,
        thumb_url: freshThumb,
        preview_expires_at: expiresAt,
      });
    }
    return res.url;
  }

  async function refreshFileUrls() {
    if (!convId.value) return;
    try {
      files.value = await api.get<ConversationFile[]>(`/conversations/${convId.value}/files`);
    } catch {
      /* ignore transient refresh failure */
    }
  }

  async function fetchPreviewContent(fileId: string, targetConvId?: string): Promise<PreviewContentResult> {
    const cid = targetConvId ?? convId.value;
    if (!cid) throw new Error("未关联对话");
    const res = await api.get<unknown>(`/conversations/${cid}/files/${fileId}/preview-content`);
    if (typeof res === "string") {
      return { content: res };
    }
    if (res && typeof res === "object") {
      const obj = res as Record<string, unknown>;
      const content =
        typeof obj.content === "string"
          ? obj.content
          : typeof obj.text === "string"
            ? obj.text
            : JSON.stringify(obj, null, 2);
      return {
        content,
        truncated: Boolean(obj.truncated),
        mime_type: typeof obj.mime_type === "string" ? obj.mime_type : undefined,
        filename: typeof obj.filename === "string" ? obj.filename : undefined,
        ext: typeof obj.ext === "string" ? obj.ext : undefined,
      };
    }
    return { content: "" };
  }

  async function fetchLibraryFiles(opts?: { q?: string; page?: number; page_size?: number }): Promise<LibraryFileItem[]> {
    const params = new URLSearchParams();
    if (opts?.q?.trim()) params.set("q", opts.q.trim());
    params.set("page", String(opts?.page ?? 1));
    params.set("page_size", String(opts?.page_size ?? 40));
    const res = await api.get<unknown>(`/library/files?${params.toString()}`);
    if (Array.isArray(res)) return res as LibraryFileItem[];
    if (res && typeof res === "object" && Array.isArray((res as any).items)) {
      return (res as any).items as LibraryFileItem[];
    }
    return [];
  }

  async function uploadToLibrary(
    inputFiles: FileList | File[],
    dataTransfer?: DataTransfer | null,
    onProgress?: (item: { filename: string; progress: number; status: "signing" | "uploading" | "completing" | "done" | "failed"; error?: string }) => void,
  ): Promise<{ uploaded: LibraryFileItem[]; errors: string[] }> {
    const { accepted, rejected } = validateSelectedFiles(inputFiles, dataTransfer);
    const errors: string[] = rejected.map((r) => `${r.filename}（${r.reason}）`);
    const uploaded: LibraryFileItem[] = [];
    const concurrency = 3;
    let idx = 0;

    const workers = Array.from({ length: Math.min(concurrency, accepted.length) }, async () => {
      while (idx < accepted.length) {
        const file = accepted[idx++];
        if (!file) break;
        try {
          onProgress?.({ filename: file.name, progress: 0, status: "signing" });
          const presign = await api.post<PresignResponse>("/library/files/presign", {
            filename: file.name,
            mime_type: file.type || "",
            size_bytes: file.size,
          });
          onProgress?.({ filename: file.name, progress: 1, status: "uploading" });
          const { etag } = await putToCos(
            presign.upload_url,
            presign.headers,
            file,
            (pct) => onProgress?.({ filename: file.name, progress: pct, status: "uploading" }),
            () => {},
          );
          onProgress?.({ filename: file.name, progress: 100, status: "completing" });
          const completed = await api.post<LibraryFileItem>(`/library/files/${presign.file_id}/complete`, { etag });
          uploaded.push(completed);
          onProgress?.({ filename: file.name, progress: 100, status: "done" });
        } catch (e: any) {
          const msg = errorText(e, "上传失败");
          errors.push(`${file.name}：${msg}`);
          onProgress?.({ filename: file.name, progress: 0, status: "failed", error: msg });
        }
      }
    });
    await Promise.all(workers);
    return { uploaded, errors };
  }

  async function attachLibraryFiles(
    fileIds: string[],
    targetConvId?: string,
    attachToMessage = true,
  ): Promise<ConversationFile[]> {
    const cid = targetConvId ?? convId.value;
    if (!cid || !fileIds.length) return [];
    const res = await api.post<ConversationFile[] | { files?: ConversationFile[] }>(
      `/conversations/${cid}/files/attach`,
      { file_ids: fileIds },
    );
    const attachedList = Array.isArray(res) ? res : Array.isArray(res?.files) ? res.files : [];
    for (const f of attachedList) {
      const idx = files.value.findIndex((item) => item.id === f.id);
      if (idx >= 0) {
        const next = [...files.value];
        next[idx] = { ...next[idx], ...f };
        files.value = next;
      } else {
        files.value = [...files.value, f];
      }
      if (attachToMessage && !attachedIds.value.includes(f.id)) {
        attachedIds.value = [...attachedIds.value, f.id];
      }
    }
    return attachedList;
  }

  return {
    convId,
    listScope,
    files,
    uploads,
    activeUploads,
    hasActiveUploads,
    fileCount,
    attachedIds,
    attachedFiles,
    loading,
    error,
    clearError,
    reset,
    load,
    enqueueFiles,
    retryUpload,
    cancelUpload,
    dismissUpload,
    detachFile,
    consumeAttachedIds,
    upsertFile,
    createTextFile,
    updateFileContent,
    renameFile,
    removeFile,
    removeLocalFile,
    patchLocalIndexStatus,
    getDownloadUrl,
    ensureFreshUrl,
    refreshFileUrls,
    fetchPreviewContent,
    fetchLibraryFiles,
    uploadToLibrary,
    attachLibraryFiles,
  };
});
