# Whitz Desktop

Windows 桌面端（Electron + electron-vite + Vue 3）。

## 目录结构

- `src/main/`：主进程（配置、认证、策略校验、OpenCode 运行时、SQLite 工作区、PTY、更新器）
- `src/preload/`：预加载桥接
- `src/renderer/`：渲染层 UI
- `src/shared/`：IPC 契约与类型（`ipc-contract.ts`、`work-types.ts`）
- `tests/`：`node --test` 测试（含 IPC 契约对齐校验）

## 命令

```bash
npm ci
npm run dev
npm run typecheck
npm test
npm run dist:win   # 打包 NSIS 安装包
```

> `npm ci` 的 postinstall 会重建 `better-sqlite3` 等原生依赖。
