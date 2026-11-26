import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const p = path.resolve(import.meta.dirname, "../src/lib/fileTokens.ts");
const m = await import(`file:///${p.replace(/\\/g, "/")}`);

const ID = "123e4567-e89b-12d3-a456-426614174000";
const ID2 = "223e4567-e89b-12d3-a456-426614174000";

test("serializeFileToken escapes ] and | and falls back to 'file'", () => {
  assert.equal(m.serializeFileToken(ID, "a]b|c.txt"), `[[file:${ID}|a)b-c.txt]]`);
  assert.equal(m.serializeFileToken(ID, "   "), `[[file:${ID}|file]]`);
});

test("parseInlineFileSegments splits text and file tokens", () => {
  assert.deepEqual(m.parseInlineFileSegments(""), []);
  const segs = m.parseInlineFileSegments(`hi [[file:${ID}|a.txt]] bye`);
  assert.deepEqual(segs, [
    { type: "text", text: "hi " },
    { type: "file", fileId: ID, filename: "a.txt" },
    { type: "text", text: " bye" },
  ]);
  assert.deepEqual(m.parseInlineFileSegments("plain"), [{ type: "text", text: "plain" }]);
});

test("extractFileIdsFromText deduplicates ids in order", () => {
  const text = `[[file:${ID}|a]] [[file:${ID2}|b]] [[file:${ID}|a]]`;
  assert.deepEqual(m.extractFileIdsFromText(text), [ID, ID2]);
  assert.deepEqual(m.extractFileIdsFromText(""), []);
});

test("hasInlineFileTokens", () => {
  assert.equal(m.hasInlineFileTokens(`x [[file:${ID}|a]]`), true);
  assert.equal(m.hasInlineFileTokens("[[file:bad|a]]"), false);
  assert.equal(m.hasInlineFileTokens(""), false);
});

test("isImageExt and isWritableTextExt", () => {
  assert.equal(m.isImageExt(".PNG"), true);
  assert.equal(m.isImageExt(".txt"), false);
  assert.equal(m.isImageExt(".txt", "image"), true);
  assert.equal(m.isImageExt(null), false);
  assert.equal(m.isWritableTextExt(".MD"), true);
  assert.equal(m.isWritableTextExt(".exe"), false);
  assert.equal(m.isWritableTextExt(undefined), false);
});
