import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";

// Lightweight runtime checks for pure Diff parsing & ANSI stripping by transpiling/loading TS via Node 24 strip-types
const diffModPath = path.resolve(import.meta.dirname, "../src/renderer/lib/unifiedDiff.ts");
const { parseUnifiedDiff, buildFallbackPatch, stripAnsi } = await import(`file:///${diffModPath.replace(/\\/g, "/")}`);

test("parseUnifiedDiff parses hunks, line numbers, additions, deletions and split alignment", () => {
  const patch = [
    "--- a/src/demo.ts",
    "+++ b/src/demo.ts",
    "@@ -10,4 +10,5 @@ export function demo() {",
    " const a = 1;",
    "-const b = 2;",
    "+const b = 3;",
    "+const c = 4;",
    " return a + b;",
  ].join("\n");

  const res = parseUnifiedDiff(patch);
  assert.equal(res.additions, 2);
  assert.equal(res.deletions, 1);
  assert.equal(res.lines.filter((l) => l.kind === "hunk").length, 1);

  const delLine = res.lines.find((l) => l.kind === "del");
  assert.equal(delLine?.oldLine, 11);
  assert.equal(delLine?.newLine, null);
  assert.equal(delLine?.text, "const b = 2;");

  const addLines = res.lines.filter((l) => l.kind === "add");
  assert.equal(addLines.length, 2);
  assert.equal(addLines[0].newLine, 11);
  assert.equal(addLines[1].newLine, 12);

  // Split view pairs contiguous del/add rows neatly
  const pairRows = res.splitRows.filter((r) => r.kind === "pair");
  assert.equal(pairRows.length, 4);
  assert.equal(pairRows[1].left.kind, "del");
  assert.equal(pairRows[1].right.kind, "add");
  assert.equal(pairRows[2].left.kind, "empty");
  assert.equal(pairRows[2].right.kind, "add");
});

test("buildFallbackPatch produces parseable unified diff", () => {
  const patch = buildFallbackPatch("foo.txt", "old1\nold2", "new1");
  const parsed = parseUnifiedDiff(patch);
  assert.equal(parsed.deletions, 2);
  assert.equal(parsed.additions, 1);
});

test("stripAnsi removes CSI and OSC escape codes cleanly", () => {
  const raw = "\x1b[32mPASS\x1b[0m tests/app.test.ts \x1b]0;title\x07ok";
  assert.equal(stripAnsi(raw), "PASS tests/app.test.ts ok");
});

test("main and preload contracts remain aligned across WorkApi channels", () => {
  const contract = fs.readFileSync(path.resolve(import.meta.dirname, "../src/shared/ipc-contract.ts"), "utf-8");
  const preload = fs.readFileSync(path.resolve(import.meta.dirname, "../src/preload/index.ts"), "utf-8");
  const handlers = fs.readFileSync(path.resolve(import.meta.dirname, "../src/main/ipc/workHandlers.ts"), "utf-8");
  const register = fs.readFileSync(path.resolve(import.meta.dirname, "../src/main/ipc/register.ts"), "utf-8");

  const requiredChannels = [
    "appSetThemeOverlay",
    "runtimeUpgrade",
    "workClarifyReject",
    "workShare",
    "workUnshare",
    "workRemoteSessions",
    "workImportSession",
    "workSubsessionMessages",
    "workSaveClipboardImage",
    "opencodeProviderCatalog",
    "opencodeProviderOAuthStart",
    "opencodeProviderOAuthCallback",
    "opencodeMcpAuth",
    "opencodeFormatterStatus",
    "ptyShells",
    "ptyCreate",
    "ptyConnectInfo",
    "worktreeCreate",
    "workspaceFindText",
    "workspaceFindSymbols",
    "workspaceGitRevertFile",
  ];

  for (const ch of requiredChannels) {
    assert.ok(contract.includes(`${ch}:`), `IPC contract missing ${ch}`);
    assert.ok(preload.includes(`IPC.${ch}`), `Preload bridge missing IPC.${ch}`);
    assert.ok(
      handlers.includes(`IPC.${ch}`) || register.includes(`IPC.${ch}`),
      `Main IPC handler missing IPC.${ch}`,
    );
  }
});
