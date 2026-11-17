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
import type { ConversationFile, UploadTask } from "../types";

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

export const useFilesStore = defineStore("files", () => {
  const convId = ref<string | null>(null);
  const files = ref<ConversationFile[]>([]);
  const uploads = ref<UploadTask[]>([]);
  const attachedIds = ref<string[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const abortMap = new Map<string, () => void>();

  const activeUploads = computed(() =>
    uploads.value.filter((u) => u.status === "signing" || u.status === "uploading" || u.status === "completing"),
  );
  const hasActiveUploads = computed(() => activeUploads.value.length > 0);
  const fileCount = computed(() => files.value.length);
  const attachedFiles = computed(() => {
    const idSet = new Set(attachedIds.value);
    return files.value.filter((f) => idSet.has(f.id));
  });

  function clearError() {
    error.value = null;
  }

  function reset() {
    for (const abort of abortMap.values()) {
      abort();
    }
    abortMap.clear();
    convId.value = null;
    files.value = [];
    uploads.value = [];
    attachedIds.value = [];
    loading.value = false;
    error.value = null;
  }

  async function load(conversationId: string) {
    if (convId.value !== conversationId) {
      for (const abort of abortMap.values()) abort();
      abortMap.clear();
      uploads.value = [];
      attachedIds.value = [];
      error.value = null;
    }
    convId.value = conversationId;
    loading.value = true;
    try {
      files.value = await api.get<ConversationFile[]>(`/conversations/${conversationId}/files`);
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

  async function runUploadTask(targetConvId: string, taskId: string, file: File) {
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

      if (convId.value === targetConvId) {
        files.value = [...files.value.filter((f) => f.id !== completed.id), completed];
        if (!attachedIds.value.includes(completed.id)) {
          attachedIds.value = [...attachedIds.value, completed.id];
        }
      }
      uploads.value = uploads.value.filter((u) => u.localId !== taskId);
    } catch (e: any) {
      abortMap.delete(taskId);
      if (e?.name === "AbortError") {
        uploads.value = uploads.value.filter((u) => u.localId !== taskId);
        return;
      }
      const cur = findTask();
      if (cur) {
        cur.status = "error";
        cur.error = errorText(e, "上传失败");
      }
      error.value = errorText(e, `${file.name} 上传失败`);
    }
  }

  async function enqueueFiles(
    inputFiles: FileList | File[],
    ensureConversation: () => Promise<string>,
    dataTransfer?: DataTransfer | null,
  ): Promise<boolean> {
    error.value = null;
    const { accepted, rejected } = validateSelectedFiles(inputFiles, dataTransfer);
    setRejectionMessage(rejected);
    if (!accepted.length) return false;

    const currentUsed = files.value.length + activeUploads.value.length;
    const remainingSlots = Math.max(0, MAX_FILES_PER_CONVERSATION - currentUsed);
    if (remainingSlots <= 0) {
      error.value = `当前对话最多保留 ${MAX_FILES_PER_CONVERSATION} 个文件，请先删除部分文件后再上传`;
      return false;
    }

    const queue = accepted.slice(0, remainingSlots);
    if (accepted.length > remainingSlots) {
      error.value = `超出单对话 ${MAX_FILES_PER_CONVERSATION} 个文件上限，仅保留前 ${remainingSlots} 个文件`;
    }

    let targetConvId: string;
    try {
      targetConvId = await ensureConversation();
      convId.value = targetConvId;
    } catch (e: any) {
      error.value = errorText(e, "无法创建对话以保存文件");
      return false;
    }

    const createdTasks: { taskId: string; file: File }[] = [];
    for (const file of queue) {
      const taskId = `up-${Date.now()}-${uploadSeq++}`;
      const spec = getFileSpec(file.name);
      uploads.value = [
        ...uploads.value,
        {
          localId: taskId,
          filename: file.name,
          ext: spec?.ext ?? getFileExt(file.name),
          category: spec?.category ?? "document",
          sizeBytes: file.size,
          progress: 0,
          status: "signing",
          file,
        },
      ];
      createdTasks.push({ taskId, file });
    }

    // 限制并发直传数（最多 3 个并发）
    const concurrency = 3;
    let idx = 0;
    const workers = Array.from({ length: Math.min(concurrency, createdTasks.length) }, async () => {
      while (idx < createdTasks.length) {
        const next = createdTasks[idx++];
        if (!next) break;
        await runUploadTask(targetConvId, next.taskId, next.file);
      }
    });
    await Promise.all(workers);
    return true;
  }

  function cancelUpload(localId: string) {
    const abort = abortMap.get(localId);
    if (abort) {
      abort();
      abortMap.delete(localId);
    }
    uploads.value = uploads.value.filter((u) => u.localId !== localId);
  }

  function dismissUpload(localId: string) {
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

  async function removeFile(fileId: string) {
    if (!convId.value) return;
    await api.delete(`/conversations/${convId.value}/files/${fileId}`);
    files.value = files.value.filter((f) => f.id !== fileId);
    attachedIds.value = attachedIds.value.filter((id) => id !== fileId);
  }

  async function getDownloadUrl(fileId: string, inline = false): Promise<string | null> {
    if (!convId.value) return null;
    const res = await api.get<{ url: string; expires_in: number }>(
      `/conversations/${convId.value}/files/${fileId}/download-url?inline=${inline ? "true" : "false"}`,
    );
    return res.url;
  }

  return {
    convId,
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
    cancelUpload,
    dismissUpload,
    detachFile,
    consumeAttachedIds,
    removeFile,
    getDownloadUrl,
  };
});
