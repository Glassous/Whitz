import crypto from "node:crypto";
import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { dialog, shell } from "electron";
import { storagePaths } from "../config";
import { getMainWindow } from "../window";
import {
  getActiveWorkspacePath,
  getWorkspaceByPath,
  listWorkspaces,
  removeWorkspace,
  setActiveWorkspacePath,
  upsertWorkspace,
} from "./repository";
import type {
  WorkAttachment,
  WorkWorkspace,
  WorkspaceEntry,
  WorkspaceFileContent,
  WorkspaceGitChange,
  WorkspaceGitStatus,
} from "../../shared/work-types";

const execFileAsync = promisify(execFile);

const IGNORED_DIRS = new Set([
  ".git",
  "node_modules",
  "__pycache__",
  ".venv",
  "venv",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".next",
  ".nuxt",
  "dist",
  "out",
  "release",
  "target",
  ".idea",
]);

const MAX_READ_BYTES = 512 * 1024;
const MAX_TREE_ENTRIES = 400;
const MAX_SEARCH_FILES = 1500;

const LANG_BY_EXT: Record<string, string> = {
  ".ts": "typescript",
  ".tsx": "tsx",
  ".js": "javascript",
  ".jsx": "jsx",
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".vue": "vue",
  ".py": "python",
  ".rs": "rust",
  ".go": "go",
  ".java": "java",
  ".cs": "csharp",
  ".cpp": "cpp",
  ".c": "c",
  ".h": "c",
  ".hpp": "cpp",
  ".json": "json",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".toml": "toml",
  ".md": "markdown",
  ".css": "css",
  ".scss": "scss",
  ".html": "html",
  ".xml": "xml",
  ".sql": "sql",
  ".sh": "bash",
  ".ps1": "powershell",
  ".bat": "batch",
  ".cmd": "batch",
  ".env": "dotenv",
};

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]);

export function getActiveWorkspace(): WorkWorkspace | null {
  const current = getActiveWorkspacePath();
  if (!current || !fs.existsSync(current)) return null;
  try {
    if (!fs.statSync(current).isDirectory()) return null;
  } catch {
    return null;
  }
  return getWorkspaceByPath(current) ?? upsertWorkspace(current);
}

export function listSavedWorkspaces(): WorkWorkspace[] {
  return listWorkspaces().filter((w) => {
    try {
      return fs.existsSync(w.path) && fs.statSync(w.path).isDirectory();
    } catch {
      return false;
    }
  });
}

export function selectWorkspace(dirPath: string): WorkWorkspace {
  const resolved = path.resolve(dirPath);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) {
    throw new Error("所选文件夹不存在或不可访问");
  }
  const ws = upsertWorkspace(resolved);
  setActiveWorkspacePath(resolved);
  return ws;
}

export function deleteWorkspace(dirPath: string): void {
  removeWorkspace(dirPath);
}

export async function pickWorkspaceFolder(): Promise<WorkWorkspace | null> {
  const win = getMainWindow();
  const options: Electron.OpenDialogOptions = {
    title: "选择本地工作区文件夹",
    properties: ["openDirectory", "createDirectory"],
    defaultPath: getActiveWorkspacePath() ?? undefined,
  };
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  if (result.canceled || !result.filePaths.length) return null;
  return selectWorkspace(result.filePaths[0]);
}

export async function openInExplorer(targetPath?: string): Promise<void> {
  const ws = getActiveWorkspace();
  let resolved = ws?.path ?? "";
  if (targetPath) {
    resolved = path.isAbsolute(targetPath)
      ? path.resolve(targetPath)
      : ws
        ? resolveWithinWorkspace(ws.path, targetPath)
        : path.resolve(targetPath);
  }
  if (!resolved || !fs.existsSync(resolved)) {
    throw new Error("路径不存在");
  }
  const stat = fs.statSync(resolved);
  if (stat.isDirectory()) {
    await shell.openPath(resolved);
  } else {
    shell.showItemInFolder(resolved);
  }
}

export function resolveWithinWorkspace(rootDir: string, relPath = ""): string {
  const rootReal = fs.realpathSync(path.resolve(rootDir));
  const cleaned = relPath.replace(/^[\\/]+/, "");
  const candidate = path.resolve(rootReal, cleaned);
  const relative = path.relative(rootReal, candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("路径超出当前工作区范围");
  }
  if (fs.existsSync(candidate)) {
    const candidateReal = fs.realpathSync(candidate);
    const realRel = path.relative(rootReal, candidateReal);
    if (realRel.startsWith("..") || path.isAbsolute(realRel)) {
      throw new Error("符号链接指向当前工作区之外");
    }
    return candidateReal;
  }
  return candidate;
}

export function listDirectoryTree(relDir = "", includeHidden = false): WorkspaceEntry[] {
  const ws = getActiveWorkspace();
  if (!ws) return [];
  const targetDir = resolveWithinWorkspace(ws.path, relDir);
  if (!fs.existsSync(targetDir) || !fs.statSync(targetDir).isDirectory()) return [];

  const entries = fs.readdirSync(targetDir, { withFileTypes: true });
  const result: WorkspaceEntry[] = [];

  for (const entry of entries) {
    if (!includeHidden && entry.name.startsWith(".") && entry.name !== ".env.example") continue;
    if (entry.isDirectory() && IGNORED_DIRS.has(entry.name)) continue;
    const full = path.join(targetDir, entry.name);
    let size = 0;
    let mtime = "";
    try {
      const stat = fs.statSync(full);
      size = stat.size;
      mtime = stat.mtime.toISOString();
    } catch {
      continue;
    }
    const relPath = path.relative(ws.path, full).split(path.sep).join("/");
    result.push({
      name: entry.name,
      rel_path: relPath,
      kind: entry.isDirectory() ? "dir" : "file",
      size,
      mtime,
    });
    if (result.length >= MAX_TREE_ENTRIES) break;
  }

  result.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });
  return result;
}

export function searchWorkspaceFiles(query: string): string[] {
  const ws = getActiveWorkspace();
  if (!ws) return [];
  const q = query.trim().toLowerCase();
  const rootReal = fs.realpathSync(ws.path);
  const queue: string[] = [rootReal];
  const matches: string[] = [];
  let scanned = 0;

  while (queue.length && scanned < MAX_SEARCH_FILES && matches.length < 40) {
    const dir = queue.shift()!;
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (entry.name.startsWith(".") && entry.name !== ".env.example") continue;
      if (entry.isDirectory()) {
        if (!IGNORED_DIRS.has(entry.name)) queue.push(path.join(dir, entry.name));
        continue;
      }
      scanned += 1;
      const full = path.join(dir, entry.name);
      const rel = path.relative(rootReal, full).split(path.sep).join("/");
      if (!q || rel.toLowerCase().includes(q)) {
        matches.push(rel);
        if (matches.length >= 40) break;
      }
    }
  }
  return matches;
}

export function readWorkspaceFile(relPath: string): WorkspaceFileContent {
  const ws = getActiveWorkspace();
  if (!ws) throw new Error("请先选择本地工作区文件夹");
  const abs = resolveWithinWorkspace(ws.path, relPath);
  if (!fs.existsSync(abs) || !fs.statSync(abs).isFile()) {
    throw new Error("文件不存在");
  }
  const stat = fs.statSync(abs);
  const fd = fs.openSync(abs, "r");
  const readLen = Math.min(stat.size, MAX_READ_BYTES);
  const buf = Buffer.alloc(readLen);
  try {
    fs.readSync(fd, buf, 0, readLen, 0);
  } finally {
    fs.closeSync(fd);
  }
  const sampleLen = Math.min(buf.length, 8192);
  let binary = false;
  for (let i = 0; i < sampleLen; i += 1) {
    if (buf[i] === 0) {
      binary = true;
      break;
    }
  }
  const ext = path.extname(abs).toLowerCase();
  const normalizedRel = path.relative(ws.path, abs).split(path.sep).join("/");
  if (IMAGE_EXTS.has(ext) || ext === ".svg") {
    const mime =
      ext === ".png"
        ? "image/png"
        : ext === ".webp"
          ? "image/webp"
          : ext === ".gif"
            ? "image/gif"
            : ext === ".svg"
              ? "image/svg+xml"
              : "image/jpeg";
    if (stat.size <= 4 * 1024 * 1024) {
      const dataUrl = `data:${mime};base64,${fs.readFileSync(abs).toString("base64")}`;
      return {
        rel_path: normalizedRel,
        abs_path: abs,
        content: dataUrl,
        language: "image",
        size: stat.size,
        truncated: false,
        binary: false,
      };
    }
  }
  return {
    rel_path: normalizedRel,
    abs_path: abs,
    content: binary ? "" : buf.toString("utf-8"),
    language: LANG_BY_EXT[ext] ?? "plaintext",
    size: stat.size,
    truncated: stat.size > MAX_READ_BYTES,
    binary,
  };
}

export async function openFileInEditor(relPath: string): Promise<void> {
  const ws = getActiveWorkspace();
  if (!ws) throw new Error("请先选择本地工作区文件夹");
  const abs = resolveWithinWorkspace(ws.path, relPath);
  if (!fs.existsSync(abs)) throw new Error("文件不存在");
  await shell.openPath(abs);
}

export async function revertGitFile(relPath: string): Promise<void> {
  const ws = getActiveWorkspace();
  if (!ws) throw new Error("请先选择本地工作区文件夹");
  const safe = resolveWithinWorkspace(ws.path, relPath);
  const rel = path.relative(fs.realpathSync(ws.path), safe).split(path.sep).join("/");
  // Check if tracked
  try {
    await runGit(ws.path, ["ls-files", "--error-unmatch", "--", rel]);
    await runGit(ws.path, ["checkout", "HEAD", "--", rel]);
  } catch {
    // Untracked file -> move to OS trash safely
    if (fs.existsSync(safe)) {
      await shell.trashItem(safe);
    }
  }
}

async function runGit(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", args, {
    cwd,
    windowsHide: true,
    timeout: 10_000,
    maxBuffer: 2 * 1024 * 1024,
  });
  return stdout;
}

export async function getGitStatus(): Promise<WorkspaceGitStatus> {
  const ws = getActiveWorkspace();
  if (!ws) return { is_repo: false, branch: null, changes: [] };
  try {
    const inside = (await runGit(ws.path, ["rev-parse", "--is-inside-work-tree"])).trim();
    if (inside !== "true") return { is_repo: false, branch: null, changes: [] };
  } catch {
    return { is_repo: false, branch: null, changes: [] };
  }

  let branch: string | null = null;
  try {
    branch = (await runGit(ws.path, ["rev-parse", "--abbrev-ref", "HEAD"])).trim() || null;
  } catch {
    branch = null;
  }

  const raw = await runGit(ws.path, ["status", "--porcelain=v1", "-uall"]);
  const changes: WorkspaceGitChange[] = [];
  for (const line of raw.split(/\r?\n/)) {
    if (!line || line.length < 4) continue;
    const x = line[0];
    const y = line[1];
    let filePath = line.slice(3).trim();
    if (filePath.includes(" -> ")) {
      filePath = filePath.split(" -> ").pop() ?? filePath;
    }
    const unquoted = filePath.replace(/^"|"$/g, "");
    changes.push({
      path: unquoted,
      status: x !== " " && x !== "?" ? `${x}${y}`.trim() : y === "?" ? "??" : y,
      staged: x !== " " && x !== "?",
    });
    if (changes.length >= 300) break;
  }

  return { is_repo: true, branch, changes };
}

export async function getGitDiff(relPath?: string): Promise<string> {
  const ws = getActiveWorkspace();
  if (!ws) return "";
  try {
    const args = ["diff", "HEAD", "--no-color"];
    if (relPath) {
      const safe = resolveWithinWorkspace(ws.path, relPath);
      const rel = path.relative(fs.realpathSync(ws.path), safe).split(path.sep).join("/");
      args.push("--", rel);
    }
    let diff = await runGit(ws.path, args);
    if (!diff.trim() && relPath) {
      // Fallback for untracked / unstaged files against index or empty.
      const safe = resolveWithinWorkspace(ws.path, relPath);
      const rel = path.relative(fs.realpathSync(ws.path), safe).split(path.sep).join("/");
      diff = await runGit(ws.path, ["diff", "--no-color", "--", rel]).catch(() => "");
      if (!diff.trim() && fs.existsSync(safe) && fs.statSync(safe).isFile()) {
        const content = readWorkspaceFile(rel);
        if (!content.binary) {
          diff = `--- /dev/null\n+++ b/${rel}\n@@ -0,0 +1,${content.content.split(/\r?\n/).length} @@\n${content.content
            .split(/\r?\n/)
            .slice(0, 400)
            .map((l) => `+${l}`)
            .join("\n")}`;
        }
      }
    }
    return diff.slice(0, 200_000);
  } catch {
    return "";
  }
}

function buildAttachmentFromPath(filePath: string): WorkAttachment | null {
  try {
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) return null;
    const ext = path.extname(filePath).toLowerCase();
    const isImage = IMAGE_EXTS.has(ext);
    let previewUrl: string | undefined;
    if (isImage && stat.size <= 4 * 1024 * 1024) {
      const mime =
        ext === ".png"
          ? "image/png"
          : ext === ".webp"
            ? "image/webp"
            : ext === ".gif"
              ? "image/gif"
              : "image/jpeg";
      previewUrl = `data:${mime};base64,${fs.readFileSync(filePath).toString("base64")}`;
    }
    return {
      id: crypto.randomUUID(),
      name: path.basename(filePath),
      path: filePath,
      kind: isImage ? "image" : "file",
      size: stat.size,
      preview_url: previewUrl,
    };
  } catch {
    return null;
  }
}

export function attachmentsFromPaths(filePaths: string[]): WorkAttachment[] {
  const out: WorkAttachment[] = [];
  for (const p of filePaths.slice(0, 10)) {
    if (typeof p !== "string" || !p.trim()) continue;
    const att = buildAttachmentFromPath(path.resolve(p));
    if (att) out.push(att);
  }
  return out;
}

export function saveClipboardImage(dataUrl: string, name?: string): WorkAttachment {
  const match = /^data:(image\/(?:png|jpeg|jpg|webp|gif));base64,(.+)$/i.exec(dataUrl.trim());
  if (!match) throw new Error("剪贴板图片格式不受支持");
  const mime = match[1].toLowerCase();
  const buf = Buffer.from(match[2], "base64");
  if (buf.length > 10 * 1024 * 1024) throw new Error("图片大小超过 10MB 限制");
  const ext = mime === "image/jpeg" || mime === "image/jpg" ? ".jpg" : mime === "image/webp" ? ".webp" : mime === "image/gif" ? ".gif" : ".png";
  const dir = path.join(storagePaths().root, "clipboard");
  fs.mkdirSync(dir, { recursive: true });
  const fileName = (name?.trim() || `paste-${Date.now()}${ext}`).replace(/[\\/:*?"<>|]/g, "_");
  const target = path.join(dir, `${crypto.randomUUID().slice(0, 8)}-${fileName}`);
  fs.writeFileSync(target, buf);
  return {
    id: crypto.randomUUID(),
    name: fileName,
    path: target,
    kind: "image",
    size: buf.length,
    preview_url: buf.length <= 4 * 1024 * 1024 ? dataUrl : undefined,
  };
}

export async function pickAttachments(): Promise<WorkAttachment[]> {
  const win = getMainWindow();
  const options: Electron.OpenDialogOptions = {
    title: "选择参考文件或图片",
    properties: ["openFile", "multiSelections"],
    defaultPath: getActiveWorkspacePath() ?? undefined,
  };
  const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
  if (result.canceled || !result.filePaths.length) return [];
  return attachmentsFromPaths(result.filePaths.slice(0, 8));
}
