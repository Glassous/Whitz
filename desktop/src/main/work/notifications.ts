import { Notification } from "electron";
import { IPC_EVENTS } from "../../shared/ipc-contract";
import { broadcast } from "../ipc/common";
import { getMainWindow } from "../window";
import { getWorkSettings } from "./settings";

export function notifyWorkEvent(options: {
  title: string;
  body: string;
  conversationId?: string | null;
  force?: boolean;
}): void {
  try {
    if (!getWorkSettings().model.desktop_notifications) return;
    if (!Notification.isSupported()) return;
    const win = getMainWindow();
    const isFocused = Boolean(win && win.isVisible() && win.isFocused());
    if (isFocused && !options.force) return;

    const notification = new Notification({
      title: options.title,
      body: options.body,
      silent: false,
    });
    notification.on("click", () => {
      const targetWin = getMainWindow();
      if (targetWin) {
        if (targetWin.isMinimized()) targetWin.restore();
        targetWin.show();
        targetWin.focus();
      }
      if (options.conversationId) {
        broadcast(IPC_EVENTS.workFocusConversation, options.conversationId);
      }
    });
    notification.show();
  } catch {
    /* ignore notification errors on unsupported platforms */
  }
}
