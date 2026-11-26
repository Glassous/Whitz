# Whitz Web

主站 Web 应用（Vue 3 + TypeScript + Vite + Pinia + Tailwind v4）。

## 目录结构

- `src/api/`：HTTP 客户端、SSE、对话票据
- `src/stores/`：Pinia 状态（auth / chat / conversations / files 等）
- `src/lib/`：纯逻辑工具（`chatTime`、`fileTokens`、`fileTypes`、`streamDeltaCoalescer` 等）
- `src/components/`、`src/views/`：UI
- `tests/`：`node --test` 单元测试

## 命令

```bash
npm ci
npm run dev        # 开发服务器
npm run typecheck  # 类型检查
npm run build
npm test           # 单元测试（Node 24 原生测试 + TS strip-types）
```
