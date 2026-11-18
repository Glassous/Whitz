import { BrowserWindow, ipcMain, type IpcMainInvokeEvent } from "electron";
import { errorMessage } from "../api";
import { scoped } from "../logger";

const logger = scoped("ipc");

function isTrustedSender(event: IpcMainInvokeEvent): boolean {
  const url = event.senderFrame?.url ?? event.sender.getURL();
  if (!url) return false;
  return url.startsWith("app://whitz") || url.startsWith("http://localhost:5174");
}

export function handle(channel: string, fn: (...args: any[]) => unknown): void {
  ipcMain.handle(channel, async (event, ...args) => {
    if (!isTrustedSender(event)) {
      logger.warn("rejected ipc from untrusted sender", event.senderFrame?.url);
      throw new Error("untrusted_channel");
    }
    try {
      return await fn(...args);
    } catch (err) {
      const message = errorMessage(err, "操作失败，请稍后重试");
      logger.warn(`${channel} failed: ${message}`);
      throw new Error(message);
    }
  });
}

export function broadcast(channel: string, payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed() || win.webContents.isDestroyed()) continue;
    win.webContents.send(channel, payload);
  }
}
