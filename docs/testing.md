# 测试指南

## 总览

| 模块 | 框架 | 位置 | 命令 | 外部依赖 |
| --- | --- | --- | --- | --- |
| `server` | pytest + pytest-asyncio | `server/tests/` | `python -m pytest -q` | PostgreSQL(pgvector) `localhost:5434`（`conftest.py` 自动创建 `whitz_test` 库）；Redis 使用 `memory://` 内存实现 |
| `agent` | pytest + pytest-asyncio | `agent/tests/` | `python -m pytest -q` | 无（外部服务均被 mock） |
| `shared` | pytest | `shared/tests/` | `python -m pytest tests -q` | 无（纯函数） |
| `web` | Node 24 `node --test` | `web/tests/*.test.mjs` | `npm test` | 无 |
| `admin` | Node 24 `node --test` | `admin/tests/*.test.mjs` | `npm test` | 无（mock `localStorage` / `window` / `document`） |
| `desktop` | Node 24 `node --test` | `desktop/tests/*.test.mjs` | `npm test` | 无 |
| `android` | JUnit | `android/app/src/test/` | `./gradlew testDebugUnitTest` | Android SDK |

前端与桌面端直接以 Node 24 的 TypeScript strip-types 能力导入 `.ts` 源码，无需 Vitest/Jest。因此被测的 `lib/` 模块须保持**零运行时依赖于构建工具**（仅使用 `import type` 引入类型）。

## 本地运行

```bash
# 数据库（仅 server 测试需要）
docker compose up -d postgres

# server / agent
cd server && .venv/Scripts/python -m pytest -q
cd agent  && .venv/Scripts/python -m pytest -q

# shared（使用任一已装 httpx 的环境）
cd shared && ../server/.venv/Scripts/python -m pytest tests -q

# 前端与桌面端
for d in web admin desktop; do (cd $d && npm run typecheck && npm test); done
```

## 编写约定

- 纯逻辑测试优先：不依赖网络、数据库与时钟（需要时间时显式传入）。
- 涉及额度/套餐等配置的断言应从源码常量派生（如 `membership.PLANS`），避免魔法数字随产品调整而失效。
- `admin` 中带副作用的模块（如 `theme.ts`、`api/client.ts`）须在 `import()` 之前安装全局 mock，并在测试结束时清理定时器（`clearSession()`）。
- `server` 的 `conftest.py` 会在导入应用前设置隔离环境变量，新增测试不要在模块顶层导入 `app.*` 之前自行改动它们。

## CI

[`.github/workflows/ci-test.yml`](../.github/workflows/ci-test.yml) 在 `push`（`main`）与所有 `pull_request` 上运行 5 类任务：`frontend`（web/admin/desktop 矩阵：typecheck + test）、`shared`、`server`（挂载 `pgvector/pgvector:pg17` 服务到 5434 端口）、`agent`。
