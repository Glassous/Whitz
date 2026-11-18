import fs from "node:fs";
import path from "node:path";
import { storagePaths } from "./config";

export interface Prefs {
  forcedOffline?: boolean;
  windowWidth?: number;
  windowHeight?: number;
  windowMaximized?: boolean;
  workWindowOpen?: boolean;
  lastRoute?: string;
  telemetryDisabled?: boolean;
}

let cache: Prefs | null = null;

function file(): string {
  return path.join(storagePaths().root, "prefs.json");
}

export function readPrefs(): Prefs {
  if (cache) return cache;
  try {
    if (!fs.existsSync(file())) {
      cache = {};
      return cache;
    }
    cache = JSON.parse(fs.readFileSync(file(), "utf-8")) as Prefs;
    return cache;
  } catch {
    cache = {};
    return cache;
  }
}

export function writePrefs(patch: Partial<Prefs>): Prefs {
  const next = { ...readPrefs(), ...patch };
  cache = next;
  try {
    fs.mkdirSync(path.dirname(file()), { recursive: true });
    fs.writeFileSync(file(), JSON.stringify(next, null, 2), "utf-8");
  } catch {
    /* best effort */
  }
  return next;
}
