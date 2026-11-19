import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cli = path.join(root, "node_modules", ".bin", process.platform === "win32" ? "electron-builder.cmd" : "electron-builder");
const hasCert = Boolean(process.env.CSC_LINK && process.env.CSC_LINK.trim());

const args = ["--win", "--config", "electron-builder.yml", "--publish", "never"];
if (!hasCert) {
  args.push("--config.win.signAndEditExecutable=false");
}

const env = { ...process.env };
if (!hasCert) {
  env.CSC_IDENTITY_AUTO_DISCOVERY = "false";
}

const res = spawnSync(cli, args, {
  cwd: root,
  stdio: "inherit",
  env,
  shell: process.platform === "win32",
});

process.exit(res.status ?? 1);
