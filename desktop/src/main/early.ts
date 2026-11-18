// Must be imported before any module that resolves userData (electron-log, config).
import { app } from "electron";
import path from "node:path";

if (process.platform === "win32") {
  const localAppData = process.env.LOCALAPPDATA || app.getPath("appData");
  app.setPath("userData", path.join(localAppData, "Whitz"));
}
