import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

// Import vue BEFORE installing a fake `document`; runtime-dom probes `document` at load time.
await import("vue");

// ---- minimal browser mocks (must exist before importing theme.ts, which runs side effects) ----
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => void store.set(k, String(v)),
  removeItem: (k) => void store.delete(k),
};

let systemDark = false;
const mqListeners = [];
const winListeners = {};
globalThis.window = {
  matchMedia: () => ({
    get matches() {
      return systemDark;
    },
    addEventListener: (_e, fn) => mqListeners.push(fn),
  }),
  addEventListener: (e, fn) => (winListeners[e] = fn),
};

const classes = new Set();
const meta = { content: "", setAttribute(k, v) { if (k === "content") this.content = v; } };
globalThis.document = {
  documentElement: {
    classList: {
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      contains: (c) => classes.has(c),
    },
  },
  querySelector: () => meta,
};

const p = path.resolve(import.meta.dirname, "../src/lib/theme.ts");
const { useTheme } = await import(`file:///${p.replace(/\\/g, "/")}`);
const t = useTheme();

test("defaults to system preference (light)", () => {
  assert.equal(t.preference.value, "system");
  assert.equal(t.theme.value, "light");
  assert.equal(meta.content, "light dark");
});

test("set('dark') persists, applies class and meta", () => {
  t.set("dark");
  assert.equal(t.theme.value, "dark");
  assert.equal(store.get("whitz_theme"), "dark");
  assert.ok(classes.has("dark"));
  assert.equal(meta.content, "dark");
});

test("toggle flips resolved theme", () => {
  t.toggle();
  assert.equal(t.theme.value, "light");
  assert.equal(store.get("whitz_theme"), "light");
  assert.ok(!classes.has("dark"));
});

test("set('system') clears storage and follows OS changes", () => {
  t.set("system");
  assert.equal(store.has("whitz_theme"), false);
  systemDark = true;
  mqListeners.forEach((fn) => fn());
  assert.equal(t.theme.value, "dark");
  assert.ok(classes.has("dark"));
});

test("OS change is ignored when explicit preference is set", () => {
  t.set("light");
  systemDark = true;
  mqListeners.forEach((fn) => fn());
  assert.equal(t.theme.value, "light");
});

test("storage event from another tab syncs preference", () => {
  store.set("whitz_theme", "dark"); // another tab changed it
  winListeners.storage({ key: "whitz_theme" });
  assert.equal(t.preference.value, "dark");
  assert.equal(t.theme.value, "dark");
  winListeners.storage({ key: "unrelated" });
  assert.equal(t.preference.value, "dark");
});
