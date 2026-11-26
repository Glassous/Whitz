import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const read = (rel) => fs.readFileSync(path.join(root, rel), "utf-8");

const contract = read("src/shared/ipc-contract.ts");
const block = contract.slice(contract.indexOf("export const IPC = {"));
const body = block.slice(0, block.indexOf("} as const"));
const entries = [...body.matchAll(/^\s+(\w+):\s*"([^"]+)"/gm)].map((m) => [m[1], m[2]]);

test("IPC contract parses into a non-trivial channel table", () => {
  assert.ok(entries.length > 20, `only parsed ${entries.length} channels`);
});

test("IPC channel names are unique and well formed", () => {
  const values = entries.map(([, v]) => v);
  assert.equal(new Set(values).size, values.length, "duplicate channel string");
  assert.equal(new Set(entries.map(([k]) => k)).size, entries.length, "duplicate key");
  for (const v of values) assert.match(v, /^[a-z0-9]+(?:[:.\-][a-z0-9\-]+)+$/i, `bad channel name ${v}`);
});

test("every IPC channel is bridged by preload or used by main", () => {
  const sources = [
    read("src/preload/index.ts"),
    read("src/main/ipc/workHandlers.ts"),
    read("src/main/ipc/register.ts"),
  ].join("\n");
  const unused = entries.map(([k]) => k).filter((k) => !sources.includes(`IPC.${k}`));
  assert.deepEqual(unused, [], `unused IPC channels: ${unused.join(", ")}`);
});
