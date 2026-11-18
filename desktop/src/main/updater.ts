import { app } from "electron";
import { autoUpdater } from "electron-updater";
import { IPC_EVENTS } from "../shared/ipc-contract";
import { broadcast } from "./ipc/common";
import { scoped } from "./logger";

const logger = scoped("updater");

export function initUpdater(): void {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;
  autoUpdater.on("error", (err) => logger.warn("update error", err.message));
  autoUpdater.on("update-available", (info) => {
    logger.info("update available", info.version);
    broadcast(IPC_EVENTS.updateAvailable, { version: info.version, notes: info.releaseNotes ?? null });
  });
  autoUpdater.on("update-downloaded", (info) => {
    logger.info("update downloaded", info.version);
    broadcast(IPC_EVENTS.updateDownloaded, { version: info.version });
  });
  setTimeout(() => {
    void autoUpdater.checkForUpdates().catch((err: Error) => logger.warn("check failed", err.message));
  }, 15_000);
}

export function quitAndInstall(): void {
  if (!app.isPackaged) return;
  autoUpdater.quitAndInstall(false, true);
}

export async function checkForUpdates(): Promise<void> {
  if (!app.isPackaged) return;
  await autoUpdater.checkForUpdates();
}
