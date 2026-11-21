export const INLINE_FILE_TOKEN_RE = /\[\[file:([0-9a-fA-F-]{36})\|([^\]]+)\]\]/g;

export const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif"]);

export const WRITABLE_TEXT_EXTENSIONS = new Set([
  ".txt",
  ".md",
  ".markdown",
  ".html",
  ".htm",
  ".css",
  ".scss",
  ".js",
  ".mjs",
  ".cjs",
  ".jsx",
  ".ts",
  ".tsx",
  ".vue",
  ".py",
  ".json",
  ".jsonl",
  ".yaml",
  ".yml",
  ".xml",
  ".svg",
  ".sql",
  ".sh",
  ".bash",
  ".zsh",
  ".csv",
  ".tsv",
  ".ini",
  ".toml",
  ".log",
  ".env",
]);

export interface InlineTextSegment {
  type: "text";
  text: string;
}

export interface InlineFileSegment {
  type: "file";
  fileId: string;
  filename: string;
}

export type InlineMessageSegment = InlineTextSegment | InlineFileSegment;

export function serializeFileToken(fileId: string, filename: string): string {
  const safeName = filename.replace(/\]/g, ")").replace(/\|/g, "-").trim() || "file";
  return `[[file:${fileId}|${safeName}]]`;
}

export function parseInlineFileSegments(content: string): InlineMessageSegment[] {
  if (!content) return [];
  const segments: InlineMessageSegment[] = [];
  let lastIndex = 0;
  const re = new RegExp(INLINE_FILE_TOKEN_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", text: content.slice(lastIndex, match.index) });
    }
    segments.push({
      type: "file",
      fileId: match[1],
      filename: match[2].trim() || "file",
    });
    lastIndex = re.lastIndex;
  }
  if (lastIndex < content.length) {
    segments.push({ type: "text", text: content.slice(lastIndex) });
  }
  return segments;
}

export function extractFileIdsFromText(content: string): string[] {
  if (!content) return [];
  const seen = new Set<string>();
  const ids: string[] = [];
  const re = new RegExp(INLINE_FILE_TOKEN_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(content)) !== null) {
    const id = match[1];
    if (!seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}

export function hasInlineFileTokens(content: string): boolean {
  if (!content) return false;
  const re = new RegExp(INLINE_FILE_TOKEN_RE.source);
  return re.test(content);
}

export function isImageExt(ext?: string | null, category?: string | null): boolean {
  if (category === "image") return true;
  if (!ext) return false;
  return IMAGE_EXTENSIONS.has(ext.toLowerCase());
}

export function isWritableTextExt(ext?: string | null): boolean {
  if (!ext) return false;
  return WRITABLE_TEXT_EXTENSIONS.has(ext.toLowerCase());
}
