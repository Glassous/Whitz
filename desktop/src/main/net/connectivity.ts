import { EventEmitter } from "node:events";
import { loadConfig } from "../config";
import { readPrefs, writePrefs } from "../prefs";
import type { ConnectivityState } from "../../shared/work-types";

export const connectivityEvents = new EventEmitter();

let state: ConnectivityState = {
  online: true,
  checked_at: new Date().toISOString(),
  latency_ms: null,
  forced_offline: Boolean(readPrefs().forcedOffline),
};

export function getConnectivity(): ConnectivityState {
  return state;
}

function apply(next: ConnectivityState): ConnectivityState {
  const changed =
    next.online !== state.online ||
    next.forced_offline !== state.forced_offline ||
    next.latency_ms !== state.latency_ms;
  state = next;
  if (changed) connectivityEvents.emit("changed", state);
  return state;
}

export async function checkConnectivity(): Promise<ConnectivityState> {
  const forced = Boolean(readPrefs().forcedOffline);
  if (forced) {
    return apply({
      online: false,
      checked_at: new Date().toISOString(),
      latency_ms: null,
      forced_offline: true,
    });
  }
  const started = Date.now();
  try {
    const resp = await fetch(`${loadConfig().apiBase}/health`, {
      method: "GET",
      signal: AbortSignal.timeout(5000),
    });
    return apply({
      online: resp.ok,
      checked_at: new Date().toISOString(),
      latency_ms: Date.now() - started,
      forced_offline: false,
    });
  } catch {
    return apply({
      online: false,
      checked_at: new Date().toISOString(),
      latency_ms: null,
      forced_offline: false,
    });
  }
}

export function setForcedOffline(value: boolean): ConnectivityState {
  writePrefs({ forcedOffline: value });
  if (value) {
    return apply({
      online: false,
      checked_at: new Date().toISOString(),
      latency_ms: null,
      forced_offline: true,
    });
  }
  void checkConnectivity();
  return state;
}

let timer: NodeJS.Timeout | null = null;

export function startConnectivityWatch(intervalMs = 30_000): void {
  if (timer) return;
  void checkConnectivity();
  timer = setInterval(() => void checkConnectivity(), intervalMs);
  timer.unref?.();
}

export function stopConnectivityWatch(): void {
  if (timer) clearInterval(timer);
  timer = null;
}
