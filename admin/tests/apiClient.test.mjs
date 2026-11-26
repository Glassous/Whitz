import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => void store.set(k, String(v)),
  removeItem: (k) => void store.delete(k),
};

const p = path.resolve(import.meta.dirname, "../src/api/client.ts");
const m = await import(`file:///${p.replace(/\\/g, "/")}`);

const auth = {
  access_token: "tok",
  expires_in: 900,
  user: { id: "1", email: "a@b.c", role: "admin" },
};

test("ApiError carries status and detail", () => {
  const e = new m.ApiError(403, "forbidden");
  assert.equal(e.status, 403);
  assert.equal(e.message, "forbidden");
  assert.equal(new m.ApiError(400, { detail: "x" }).message, '{"detail":"x"}');
});

test("readableError extracts messages", () => {
  assert.equal(m.readableError(new m.ApiError(400, "bad")), "bad");
  assert.equal(m.readableError(new m.ApiError(400, { detail: "nested" })), "nested");
  assert.equal(m.readableError(new Error("boom")), "boom");
  assert.equal(m.readableError(42), "请求失败");
});

test("session set/clear round trip", () => {
  try {
    assert.equal(m.hasStoredSession(), false);
    m.setSession(auth);
    assert.equal(m.getAccessToken(), "tok");
    assert.equal(m.hasStoredSession(), true);
    assert.deepEqual(m.readStoredUser(), auth.user);
  } finally {
    m.clearSession();
  }
  assert.equal(m.getAccessToken(), null);
  assert.equal(m.readStoredUser(), null);
});

test("readStoredUser tolerates corrupt JSON", () => {
  store.set("whitz_admin_user", "{not json");
  assert.equal(m.readStoredUser(), null);
  store.clear();
});
