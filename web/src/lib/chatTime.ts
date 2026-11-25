export const CHAT_TIME_GAP_MS = 5 * 60 * 1000;

const WEEKDAYS_ZH = [
  "星期日",
  "星期一",
  "星期二",
  "星期三",
  "星期四",
  "星期五",
  "星期六",
] as const;

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/**
 * Parse an ISO-8601 (or SQLite UTC) timestamp string into epoch milliseconds.
 * Returns null for blank or invalid inputs.
 */
export function parseChatTimestampMs(iso: string | null | undefined): number | null {
  if (!iso || typeof iso !== "string") return null;
  const trimmed = iso.trim();
  if (!trimmed) return null;
  const normalized =
    /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(trimmed) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(trimmed)
      ? `${trimmed.replace(" ", "T")}Z`
      : trimmed;
  const ms = Date.parse(normalized);
  return Number.isFinite(ms) ? ms : null;
}

function localDaySerial(d: Date): number {
  return Math.floor(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / MS_PER_DAY);
}

/**
 * WeChat-style divider visibility rule:
 * Show a centered timestamp above the current message when it is the first message,
 * crosses a local calendar day boundary, or is at least 5 minutes after the previous message.
 */
export function shouldShowChatTimeDivider(
  prevIso: string | null | undefined,
  currIso: string | null | undefined,
): boolean {
  const currMs = parseChatTimestampMs(currIso);
  if (currMs === null) return false;
  const prevMs = parseChatTimestampMs(prevIso);
  if (prevMs === null) return true;

  const prevDate = new Date(prevMs);
  const currDate = new Date(currMs);
  if (localDaySerial(prevDate) !== localDaySerial(currDate)) {
    return true;
  }
  return currMs - prevMs >= CHAT_TIME_GAP_MS;
}

/**
 * Format a timestamp in WeChat Simplified Chinese chat style:
 * - Today: HH:mm
 * - Yesterday: 昨天 HH:mm
 * - 2-6 days ago: 星期X HH:mm
 * - Earlier this year: M月D日 HH:mm
 * - Other years: YYYY年M月D日 HH:mm
 */
export function formatChatDividerTime(
  iso: string | null | undefined,
  nowMs: number = Date.now(),
): string {
  const ms = parseChatTimestampMs(iso);
  if (ms === null) return "";

  const date = new Date(ms);
  const now = new Date(nowMs);
  const timePart = `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
  const dayDiff = localDaySerial(now) - localDaySerial(date);

  if (dayDiff === 0) {
    return timePart;
  }
  if (dayDiff === 1) {
    return `昨天 ${timePart}`;
  }
  if (dayDiff >= 2 && dayDiff <= 6) {
    return `${WEEKDAYS_ZH[date.getDay()]} ${timePart}`;
  }
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日 ${timePart}`;
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${timePart}`;
}
