import type { WorkPtyConnectInfo, WorkPtyInfo, WorkShellOption } from "../../shared/work-types";
import { getStatus, opencodeBaseUrl, startRuntime } from "../runtime/opencodeRuntime";
import { OpenCodeClient } from "./opencodeClient";
import { getActiveWorkspacePath } from "./repository";

async function ensureReady(): Promise<void> {
  const st = getStatus();
  if (st.running) return;
  if (!st.installed) throw new Error("未检测到本机 OpenCode CLI，无法启动终端");
  await startRuntime();
}

function resolveDir(workspacePath?: string | null): string | null {
  return workspacePath ?? getActiveWorkspacePath();
}

export async function listPtyShells(workspacePath?: string | null): Promise<WorkShellOption[]> {
  if (!getStatus().running) return [];
  try {
    return await new OpenCodeClient().listShells(resolveDir(workspacePath));
  } catch {
    return [];
  }
}

export async function listActivePtys(workspacePath?: string | null): Promise<WorkPtyInfo[]> {
  if (!getStatus().running) return [];
  try {
    return await new OpenCodeClient().listPtys(resolveDir(workspacePath));
  } catch {
    return [];
  }
}

export async function createPtySession(options?: {
  command?: string;
  args?: string[];
  cwd?: string;
  title?: string;
  workspacePath?: string | null;
}): Promise<WorkPtyInfo> {
  await ensureReady();
  const dir = resolveDir(options?.workspacePath);
  const cwd = options?.cwd || dir || undefined;
  return new OpenCodeClient().createPty(
    {
      ...(options?.command ? { command: options.command } : {}),
      ...(options?.args?.length ? { args: options.args } : {}),
      ...(cwd ? { cwd } : {}),
      ...(options?.title ? { title: options.title } : {}),
    },
    dir,
  );
}

export async function updatePtySession(
  ptyId: string,
  patch: { title?: string; size?: { rows: number; cols: number } },
  workspacePath?: string | null,
): Promise<WorkPtyInfo> {
  await ensureReady();
  return new OpenCodeClient().updatePty(ptyId, patch, resolveDir(workspacePath));
}

export async function removePtySession(ptyId: string, workspacePath?: string | null): Promise<void> {
  if (!getStatus().running) return;
  await new OpenCodeClient().removePty(ptyId, resolveDir(workspacePath));
}

export async function getPtyConnectInfo(ptyId: string, workspacePath?: string | null): Promise<WorkPtyConnectInfo> {
  await ensureReady();
  const dir = resolveDir(workspacePath);
  const client = new OpenCodeClient();
  const ticket = await client.createPtyConnectToken(ptyId, dir);
  const httpBase = opencodeBaseUrl().replace(/\/+$/, "");
  const wsBase = httpBase.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
  const params = new URLSearchParams({ ticket });
  if (dir) params.set("directory", dir);
  return {
    pty_id: ptyId,
    ticket,
    ws_url: `${wsBase}/pty/${encodeURIComponent(ptyId)}/connect?${params.toString()}`,
  };
}
