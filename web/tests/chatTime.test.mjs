import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";

const chatTimePath = path.resolve(import.meta.dirname, "../src/lib/chatTime.ts");
const {
  CHAT_TIME_GAP_MS,
  parseChatTimestampMs,
  shouldShowChatTimeDivider,
  formatChatDividerTime,
} = await import(`file:///${chatTimePath.replace(/\\/g, "/")}`);

function localIso(year, month, day, hour, minute, second = 0) {
  return new Date(year, month - 1, day, hour, minute, second, 0).toISOString();
}

test("parseChatTimestampMs handles ISO strings, SQLite UTC format, and invalid values", () => {
  assert.equal(parseChatTimestampMs(null), null);
  assert.equal(parseChatTimestampMs(""), null);
  assert.equal(parseChatTimestampMs("not-a-date"), null);

  const isoMs = parseChatTimestampMs("2026-11-25T10:30:00Z");
  assert.equal(isoMs, Date.UTC(2026, 10, 25, 10, 30, 0));

  const sqliteUtcMs = parseChatTimestampMs("2026-11-25 10:30:00");
  assert.equal(sqliteUtcMs, Date.UTC(2026, 10, 25, 10, 30, 0));
});

test("shouldShowChatTimeDivider follows WeChat rules (first, cross-day, >= 5 min)", () => {
  const t1 = localIso(2026, 11, 25, 10, 0, 0);
  const t2 = localIso(2026, 11, 25, 10, 4, 59);
  const t3 = localIso(2026, 11, 25, 10, 5, 0);
  const prevNight = localIso(2026, 11, 24, 23, 59, 0);
  const midnight = localIso(2026, 11, 25, 0, 0, 30);

  assert.equal(CHAT_TIME_GAP_MS, 5 * 60 * 1000);
  assert.equal(shouldShowChatTimeDivider(null, t1), true);
  assert.equal(shouldShowChatTimeDivider(t1, null), false);
  assert.equal(shouldShowChatTimeDivider(t1, t2), false);
  assert.equal(shouldShowChatTimeDivider(t1, t3), true);
  assert.equal(shouldShowChatTimeDivider(prevNight, midnight), true);
});

test("formatChatDividerTime formats today, yesterday, weekday, same-year, and cross-year in Chinese", () => {
  // Reference "now": Wednesday 2026-11-25 18:35 local time
  const nowMs = new Date(2026, 10, 25, 18, 35, 0, 0).getTime();

  assert.equal(formatChatDividerTime(localIso(2026, 11, 25, 9, 5), nowMs), "09:05");
  assert.equal(formatChatDividerTime(localIso(2026, 11, 24, 22, 18), nowMs), "昨天 22:18");
  assert.equal(formatChatDividerTime(localIso(2026, 11, 23, 14, 0), nowMs), "星期一 14:00");
  assert.equal(formatChatDividerTime(localIso(2026, 11, 19, 8, 30), nowMs), "星期四 08:30");
  assert.equal(formatChatDividerTime(localIso(2026, 11, 18, 8, 30), nowMs), "11月18日 08:30");
  assert.equal(formatChatDividerTime(localIso(2025, 12, 31, 23, 59), nowMs), "2025年12月31日 23:59");
  assert.equal(formatChatDividerTime("invalid", nowMs), "");
});
