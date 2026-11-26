import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const p = path.resolve(import.meta.dirname, "../src/lib/fileTypes.ts");
const m = await import(`file:///${p.replace(/\\/g, "/")}`);

test("getFileExt", () => {
  assert.equal(m.getFileExt("a.TXT"), ".txt");
  assert.equal(m.getFileExt("archive.tar.gz"), ".gz");
  assert.equal(m.getFileExt("noext"), "");
  assert.equal(m.getFileExt(".hidden"), "");
  assert.equal(m.getFileExt("trailing."), "");
  assert.equal(m.getFileExt("  a.md  "), ".md");
});

test("size limits are consistent", () => {
  assert.equal(m.MAX_FILE_SIZE_BYTES, m.MAX_FILE_SIZE_MB * 1024 * 1024);
  assert.equal(m.MAX_FILE_SIZE_MB, 20);
  assert.equal(m.MAX_FILES_PER_CONVERSATION, 20);
});

test("allowed specs are self-consistent", () => {
  for (const [key, spec] of Object.entries(m.ALLOWED_FILE_SPECS)) {
    assert.equal(spec.ext, key);
    assert.ok(key.startsWith("."));
    assert.ok(spec.mime.length > 0);
  }
  assert.equal(m.ALLOWED_FILE_SPECS[".pdf"].category, "document");
  assert.equal(m.ALLOWED_FILE_SPECS[".png"].category, "image");
  assert.equal(m.ALLOWED_FILE_SPECS[".svg"], undefined);
  assert.equal(m.ACCEPT_ATTR.split(",").length, Object.keys(m.ALLOWED_FILE_SPECS).length);
});
