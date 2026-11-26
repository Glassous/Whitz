import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const p = path.resolve(import.meta.dirname, "../src/lib/streamDeltaCoalescer.ts");
const { createDeltaCoalescer } = await import(`file:///${p.replace(/\\/g, "/")}`);

function make(intervalMs = 10) {
  const flushed = [];
  const c = createDeltaCoalescer({
    intervalMs,
    createEmpty: () => ({ text: "" }),
    append: (b, chunk) => {
      b.text += chunk;
    },
    isEmpty: (b) => b.text === "",
    onFlush: (b) => flushed.push(b.text),
  });
  return { c, flushed };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test("batches chunks and flushes on timer", async () => {
  const { c, flushed } = make();
  c.push("a");
  c.push("b");
  assert.equal(c.hasPending(), true);
  assert.deepEqual(flushed, []);
  await sleep(40);
  assert.deepEqual(flushed, ["ab"]);
  assert.equal(c.hasPending(), false);
});

test("flushNow flushes synchronously and cancels timer", async () => {
  const { c, flushed } = make();
  c.push("x");
  c.flushNow();
  assert.deepEqual(flushed, ["x"]);
  await sleep(30);
  assert.deepEqual(flushed, ["x"]);
  c.flushNow();
  assert.deepEqual(flushed, ["x"]);
});

test("clear drops pending data", async () => {
  const { c, flushed } = make();
  c.push("x");
  c.clear();
  assert.equal(c.hasPending(), false);
  await sleep(30);
  assert.deepEqual(flushed, []);
});

test("empty chunks do not schedule a flush", async () => {
  const { c, flushed } = make();
  c.push("");
  assert.equal(c.hasPending(), false);
  await sleep(30);
  assert.deepEqual(flushed, []);
});
