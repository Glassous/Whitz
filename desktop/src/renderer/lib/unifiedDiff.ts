export interface DiffLine {
  kind: "meta" | "hunk" | "add" | "del" | "context";
  text: string;
  oldLine: number | null;
  newLine: number | null;
}

export interface SplitDiffRow {
  kind: "meta" | "hunk" | "pair";
  hunkText?: string;
  left: { kind: "del" | "context" | "empty"; line: number | null; text: string };
  right: { kind: "add" | "context" | "empty"; line: number | null; text: string };
}

export interface ParsedUnifiedDiff {
  lines: DiffLine[];
  splitRows: SplitDiffRow[];
  additions: number;
  deletions: number;
}

const ANSI_REGEX = /\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\)/g;

export function stripAnsi(input: string): string {
  return input.replace(ANSI_REGEX, "");
}

export function buildFallbackPatch(file: string, before = "", after = ""): string {
  const bLines = before ? before.split(/\r?\n/) : [];
  const aLines = after ? after.split(/\r?\n/) : [];
  const out = [`--- a/${file}`, `+++ b/${file}`, `@@ -1,${bLines.length} +1,${aLines.length} @@`];
  for (const l of bLines) out.push(`-${l}`);
  for (const l of aLines) out.push(`+${l}`);
  return out.join("\n");
}

export function parseUnifiedDiff(rawPatch: string): ParsedUnifiedDiff {
  if (!rawPatch || !rawPatch.trim()) {
    return { lines: [], splitRows: [], additions: 0, deletions: 0 };
  }
  const rawLines = rawPatch.split(/\r?\n/);
  const lines: DiffLine[] = [];
  let oldNum = 0;
  let newNum = 0;
  let additions = 0;
  let deletions = 0;

  for (const raw of rawLines) {
    if (
      raw.startsWith("diff --git") ||
      raw.startsWith("index ") ||
      raw.startsWith("--- ") ||
      raw.startsWith("+++ ") ||
      raw.startsWith("new file mode") ||
      raw.startsWith("deleted file mode") ||
      raw.startsWith("rename ") ||
      raw.startsWith("similarity ")
    ) {
      lines.push({ kind: "meta", text: raw, oldLine: null, newLine: null });
      continue;
    }

    const hunkMatch = /^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@(.*)$/.exec(raw);
    if (hunkMatch) {
      oldNum = Number.parseInt(hunkMatch[1], 10) || 1;
      newNum = Number.parseInt(hunkMatch[2], 10) || 1;
      lines.push({ kind: "hunk", text: raw, oldLine: null, newLine: null });
      continue;
    }

    if (raw.startsWith("+")) {
      additions += 1;
      lines.push({ kind: "add", text: raw.slice(1), oldLine: null, newLine: newNum });
      newNum += 1;
      continue;
    }

    if (raw.startsWith("-")) {
      deletions += 1;
      lines.push({ kind: "del", text: raw.slice(1), oldLine: oldNum, newLine: null });
      oldNum += 1;
      continue;
    }

    if (raw.startsWith("\\ No newline")) {
      lines.push({ kind: "meta", text: raw, oldLine: null, newLine: null });
      continue;
    }

    const text = raw.startsWith(" ") ? raw.slice(1) : raw;
    if (oldNum > 0 || newNum > 0) {
      lines.push({ kind: "context", text, oldLine: oldNum, newLine: newNum });
      oldNum += 1;
      newNum += 1;
    } else if (raw.trim()) {
      lines.push({ kind: "meta", text: raw, oldLine: null, newLine: null });
    }
  }

  // Build aligned side-by-side split rows
  const splitRows: SplitDiffRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.kind === "meta") {
      i += 1;
      continue;
    }
    if (line.kind === "hunk") {
      splitRows.push({
        kind: "hunk",
        hunkText: line.text,
        left: { kind: "empty", line: null, text: "" },
        right: { kind: "empty", line: null, text: "" },
      });
      i += 1;
      continue;
    }
    if (line.kind === "context") {
      splitRows.push({
        kind: "pair",
        left: { kind: "context", line: line.oldLine, text: line.text },
        right: { kind: "context", line: line.newLine, text: line.text },
      });
      i += 1;
      continue;
    }

    // Group contiguous del/add block so deletions align neatly beside additions
    const dels: DiffLine[] = [];
    const adds: DiffLine[] = [];
    while (i < lines.length && (lines[i].kind === "del" || lines[i].kind === "add")) {
      if (lines[i].kind === "del") dels.push(lines[i]);
      else adds.push(lines[i]);
      i += 1;
    }
    const max = Math.max(dels.length, adds.length);
    for (let k = 0; k < max; k += 1) {
      const d = dels[k];
      const a = adds[k];
      splitRows.push({
        kind: "pair",
        left: d
          ? { kind: "del", line: d.oldLine, text: d.text }
          : { kind: "empty", line: null, text: "" },
        right: a
          ? { kind: "add", line: a.newLine, text: a.text }
          : { kind: "empty", line: null, text: "" },
      });
    }
  }

  return { lines, splitRows, additions, deletions };
}
