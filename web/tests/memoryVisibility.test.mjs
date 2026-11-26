import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const p = path.resolve(import.meta.dirname, "../src/lib/memoryVisibility.ts");
const { isMemoryCitation } = await import(`file:///${p.replace(/\\/g, "/")}`);

test("isMemoryCitation", () => {
  assert.equal(isMemoryCitation({ source_type: "memory" }), true);
  assert.equal(isMemoryCitation({ source_type: "file" }), false);
  assert.equal(isMemoryCitation({ source_type: "" }), false);
});
