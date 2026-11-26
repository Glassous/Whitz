import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const p = path.resolve(import.meta.dirname, "../src/lib/htmlTheme.ts");
const { injectHtmlTheme } = await import(`file:///${p.replace(/\\/g, "/")}`);

test("injectHtmlTheme inserts into existing <head>", () => {
  const out = injectHtmlTheme("<!doctype html><html><head><title>x</title></head><body>hi</body></html>", true);
  assert.match(out, /<head><meta name="color-scheme" content="dark">/);
  assert.match(out, /--whitz-theme:dark/);
  assert.match(out, /<title>x<\/title>/);
});

test("injectHtmlTheme adds <head> when <html> exists without <head>", () => {
  const out = injectHtmlTheme('<html lang="zh"><body>hi</body></html>', false);
  assert.match(out, /^<html lang="zh"><head><meta name="color-scheme" content="light">/);
  assert.match(out, /--whitz-theme:light/);
});

test("injectHtmlTheme wraps bare HTML fragment", () => {
  const out = injectHtmlTheme("<p>hello</p>", true);
  assert.match(out, /^<!doctype html><html data-theme="dark" class="dark">/);
  assert.match(out, /<body><p>hello<\/p><\/body><\/html>$/);
});
