import type { FileCategory } from "../types";

export interface AllowedFileSpec {
  ext: string;
  category: FileCategory;
  mime: string;
  label: string;
}

export const MAX_FILE_SIZE_MB = 20;
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
export const MAX_FILES_PER_CONVERSATION = 20;

export const ALLOWED_FILE_SPECS: Record<string, AllowedFileSpec> = {
  // 文档
  ".pdf": { ext: ".pdf", category: "document", mime: "application/pdf", label: "PDF" },
  ".docx": {
    ext: ".docx",
    category: "document",
    mime: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    label: "Word",
  },
  ".txt": { ext: ".txt", category: "document", mime: "text/plain", label: "文本" },
  ".md": { ext: ".md", category: "document", mime: "text/markdown", label: "Markdown" },
  ".markdown": { ext: ".markdown", category: "document", mime: "text/markdown", label: "Markdown" },
  // 表格与数据
  ".xlsx": {
    ext: ".xlsx",
    category: "spreadsheet",
    mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    label: "Excel",
  },
  ".csv": { ext: ".csv", category: "spreadsheet", mime: "text/csv", label: "CSV" },
  ".tsv": { ext: ".tsv", category: "spreadsheet", mime: "text/tab-separated-values", label: "TSV" },
  ".json": { ext: ".json", category: "spreadsheet", mime: "application/json", label: "JSON" },
  ".jsonl": { ext: ".jsonl", category: "spreadsheet", mime: "application/x-ndjson", label: "JSONL" },
  ".yaml": { ext: ".yaml", category: "spreadsheet", mime: "application/x-yaml", label: "YAML" },
  ".yml": { ext: ".yml", category: "spreadsheet", mime: "application/x-yaml", label: "YAML" },
  ".xml": { ext: ".xml", category: "spreadsheet", mime: "application/xml", label: "XML" },
  // 代码与配置
  ".py": { ext: ".py", category: "code", mime: "text/x-python", label: "Python" },
  ".js": { ext: ".js", category: "code", mime: "text/javascript", label: "JS" },
  ".ts": { ext: ".ts", category: "code", mime: "text/typescript", label: "TS" },
  ".tsx": { ext: ".tsx", category: "code", mime: "text/tsx", label: "TSX" },
  ".jsx": { ext: ".jsx", category: "code", mime: "text/jsx", label: "JSX" },
  ".vue": { ext: ".vue", category: "code", mime: "text/plain", label: "Vue" },
  ".html": { ext: ".html", category: "code", mime: "text/html", label: "HTML" },
  ".css": { ext: ".css", category: "code", mime: "text/css", label: "CSS" },
  ".sql": { ext: ".sql", category: "code", mime: "application/sql", label: "SQL" },
  ".sh": { ext: ".sh", category: "code", mime: "text/x-shellscript", label: "Shell" },
  ".log": { ext: ".log", category: "code", mime: "text/plain", label: "日志" },
  ".ini": { ext: ".ini", category: "code", mime: "text/plain", label: "INI" },
  ".toml": { ext: ".toml", category: "code", mime: "application/toml", label: "TOML" },
  // 图片
  ".png": { ext: ".png", category: "image", mime: "image/png", label: "PNG" },
  ".jpg": { ext: ".jpg", category: "image", mime: "image/jpeg", label: "JPG" },
  ".jpeg": { ext: ".jpeg", category: "image", mime: "image/jpeg", label: "JPEG" },
  ".webp": { ext: ".webp", category: "image", mime: "image/webp", label: "WebP" },
  ".gif": { ext: ".gif", category: "image", mime: "image/gif", label: "GIF" },
};

export const ACCEPT_ATTR = Object.keys(ALLOWED_FILE_SPECS).join(",");

export const SUPPORTED_TYPES_SUMMARY =
  "支持文档（PDF/DOCX/TXT/MD）、表格数据（XLSX/CSV/JSON/YAML/XML）、代码文本及图片（PNG/JPG/WebP/GIF），单文件最大 20 MB";

const BLOCKED_MIME_PREFIXES = ["video/", "audio/"];
const BLOCKED_MIME_EXACT = new Set([
  "application/zip",
  "application/x-zip-compressed",
  "application/x-rar-compressed",
  "application/vnd.rar",
  "application/x-7z-compressed",
  "application/x-tar",
  "application/gzip",
  "application/x-gzip",
  "application/x-msdownload",
  "application/x-dosexec",
  "application/x-executable",
  "application/x-mach-binary",
  "image/svg+xml",
]);

const ALLOWED_DRAG_MIME_EXACT = new Set([
  ...Object.values(ALLOWED_FILE_SPECS).map((s) => s.mime),
  "application/octet-stream",
  "text/x-markdown",
  "application/x-javascript",
  "application/javascript",
  "text/xml",
  "text/yaml",
  "application/yaml",
]);

export function getFileExt(filename: string): string {
  const clean = filename.trim();
  const dot = clean.lastIndexOf(".");
  if (dot <= 0 || dot === clean.length - 1) return "";
  return clean.slice(dot).toLowerCase();
}

export function getFileSpec(filename: string): AllowedFileSpec | null {
  const ext = getFileExt(filename);
  return ext ? ALLOWED_FILE_SPECS[ext] ?? null : null;
}

export function isBlockedMime(mime: string): boolean {
  const base = mime.split(";")[0].trim().toLowerCase();
  if (!base || base === "application/octet-stream") return false;
  if (BLOCKED_MIME_PREFIXES.some((p) => base.startsWith(p))) return true;
  if (BLOCKED_MIME_EXACT.has(base)) return true;
  return false;
}

/**
 * 拖拽悬停（dragenter / dragover）阶段预检查：
 * 浏览器在 drop 前通常会隐藏文件名，但对已知音视频、压缩包、可执行程序等会暴露 MIME。
 */
export function validateDragItems(dataTransfer: DataTransfer | null): {
  hasFiles: boolean;
  valid: boolean;
  reason?: string;
} {
  if (!dataTransfer) return { hasFiles: false, valid: true };
  const types = Array.from(dataTransfer.types ?? []);
  if (!types.includes("Files")) return { hasFiles: false, valid: true };

  const items = Array.from(dataTransfer.items ?? []).filter((item) => item.kind === "file");
  if (!items.length) return { hasFiles: true, valid: true };

  for (const item of items) {
    const mime = (item.type || "").split(";")[0].trim().toLowerCase();
    if (!mime) continue; // 很多代码/Markdown 文件在 dragover 时 type 为空，留到 drop 校验扩展名
    if (isBlockedMime(mime)) {
      return {
        hasFiles: true,
        valid: false,
        reason: `包含不支持的文件类型（${mime}），${SUPPORTED_TYPES_SUMMARY}`,
      };
    }
    if (!mime.startsWith("text/") && !ALLOWED_DRAG_MIME_EXACT.has(mime)) {
      return {
        hasFiles: true,
        valid: false,
        reason: `包含不支持的文件类型（${mime}），${SUPPORTED_TYPES_SUMMARY}`,
      };
    }
  }
  return { hasFiles: true, valid: true };
}

export interface FileRejectedItem {
  filename: string;
  reason: string;
}

export function validateSelectedFiles(fileList: FileList | File[], dataTransfer?: DataTransfer | null): {
  accepted: File[];
  rejected: FileRejectedItem[];
} {
  const files = Array.from(fileList);
  const accepted: File[] = [];
  const rejected: FileRejectedItem[] = [];

  // 若是拖拽，尝试识别文件夹条目
  const items = dataTransfer?.items ? Array.from(dataTransfer.items) : [];

  files.forEach((file, idx) => {
    const entry = items[idx]?.webkitGetAsEntry?.();
    if (entry?.isDirectory) {
      rejected.push({ filename: file.name || "文件夹", reason: "暂不支持直接上传文件夹，请选取具体文件" });
      return;
    }

    const ext = getFileExt(file.name);
    const spec = ext ? ALLOWED_FILE_SPECS[ext] : undefined;
    if (!spec) {
      rejected.push({
        filename: file.name,
        reason: `不支持的文件格式（${ext || "无扩展名"}）`,
      });
      return;
    }

    const mime = (file.type || "").split(";")[0].trim().toLowerCase();
    if (mime && isBlockedMime(mime)) {
      rejected.push({ filename: file.name, reason: `不支持的文件类型（${mime}）` });
      return;
    }

    if (file.size <= 0) {
      rejected.push({ filename: file.name, reason: "空文件（0 字节）无法上传" });
      return;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      rejected.push({
        filename: file.name,
        reason: `超过单文件 ${MAX_FILE_SIZE_MB} MB 上限（当前 ${formatFileSize(file.size)}）`,
      });
      return;
    }

    accepted.push(file);
  });

  return { accepted, rejected };
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function categoryLabel(category: string, ext?: string): string {
  if (ext) {
    const spec = ALLOWED_FILE_SPECS[ext.toLowerCase()];
    if (spec) return spec.label;
  }
  switch (category) {
    case "document":
      return "文档";
    case "spreadsheet":
      return "数据";
    case "code":
      return "代码";
    case "image":
      return "图片";
    default:
      return "文件";
  }
}
