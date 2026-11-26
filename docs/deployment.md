# 部署与 CI/CD 指南

## Docker Compose 服务拓扑

仓库根目录提供两套 Compose 配置：
- [docker-compose.yml](file:///d:/.Resource/Project/Whitz/docker-compose.yml)：本地与开发环境编排。
- [docker-compose.prod.yml](file:///d:/.Resource/Project/Whitz/docker-compose.prod.yml)：生产环境编排（直接拉取镜像仓库产物，不在目标服务器执行 `docker build`）。

核心容器列表：
- `postgres`（`pgvector/pgvector:pg17`）：主数据库与向量存储，本地开发映射端口 `127.0.0.1:5434:5432`。
- `redis`（`redis:7-alpine`）：开启 AOF 持久化与 `noeviction` 策略，承载 ARQ 队列、限流与实时事件总线。
- `app-data-init`（`busybox`）：一次性初始化共享卷 `/app-data/avatars` 目录并移交属主为 `1000:1000`。
- `agent-api`（`:8642`）：Agent Control API 服务（`AGENT_ROLE=api`）。
- `agent-worker`：Agent ARQ 后台执行节点。
- `server`（`:8000`）：FastAPI 主服务，启动前执行数据库迁移与管理员初始化。

### 生产环境安全基线

启动生产环境前，务必检查以下配置：
1. 更换 `JWT_SECRET`、`AGENT_INTERNAL_TOKEN` 与 `ADMIN_PASSWORD`（可用 `openssl rand -hex 32` 生成）。
2. 启用 HTTPS 反向代理后，设置 `AUTH_COOKIE_SECURE=true` 并配置 `ALLOWED_HOSTS` 为实际域名列表。
3. 若使用桌面端策略签名，使用 `python server/scripts/gen_desktop_policy_key.py` 生成密钥对并配置 `DESKTOP_POLICY_PRIVATE_KEY`。

## GitHub Actions CI/CD 流水线

仓库 `.github/workflows/` 包含以下工作流：

| 工作流文件 | 触发条件 | 作用说明 |
| --- | --- | --- |
| [ci-test.yml](file:///d:/.Resource/Project/Whitz/.github/workflows/ci-test.yml) | `push` / `pull_request` (`main`) | 自动执行 `web`、`admin`、`desktop` 类型检查与单测，以及 `shared`、`server`（含 pgvector 服务容器）、`agent` 的 pytest，详见 [testing.md](testing.md) |
| [deploy-server.yml](file:///d:/.Resource/Project/Whitz/.github/workflows/deploy-server.yml) | `push` (`main`, `server/**`, `agent/**`, `shared/**`) | 并行构建 `server` 与 `agent` Docker 镜像，推送阿里云 ACR（不可达时自动降级 GHCR）并部署到远程主机 |
| [deploy-web.yml](file:///d:/.Resource/Project/Whitz/.github/workflows/deploy-web.yml) | `push` (`main`, `web/**`) | 构建 `web/dist` 并通过 SCP/SSH 原子替换到静态站点目录 |
| [deploy-admin.yml](file:///d:/.Resource/Project/Whitz/.github/workflows/deploy-admin.yml) | `push` (`main`, `admin/**`) | 构建 `admin/dist` 并通过 SCP/SSH 原子替换到管理后台站点目录 |
| [build-desktop.yml](file:///d:/.Resource/Project/Whitz/.github/workflows/build-desktop.yml) | `tag: desktop-v*` / 手动触发 | 在 `windows-latest` 上生成图标、类型检查、构建并打包 NSIS 安装包（`.exe`） |

## 监控与可观测性

`ops/` 目录提供 Prometheus 与 Grafana 配置：
- [prometheus.yml](file:///d:/.Resource/Project/Whitz/ops/prometheus/prometheus.yml)：采集 `server`（`/metrics`）与 `agent-api`（`/metrics`）指标。
- [ops/grafana/provisioning/datasources/prometheus.yml](file:///d:/.Resource/Project/Whitz/ops/grafana/provisioning/datasources/prometheus.yml)：自动配置 Grafana Prometheus 数据源。
