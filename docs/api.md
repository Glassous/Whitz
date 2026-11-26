# API 接口概览

## 1. Server 控制面 API（`:8000`）

`server` 基于 FastAPI 提供 REST 与 SSE 接口，交互式 OpenAPI 文档可在开发环境下访问 `/docs`。

### 鉴权方式
- **用户态接口**：`Authorization: Bearer <access_token>`，配合 `/api/auth/refresh` 使用 HttpOnly Refresh Cookie 续期。
- **管理员接口**：需具备 `admin` 角色（`require_admin`）。
- **内部接口**：`/api/internal/*` 与 `agent` 通信使用 `X-Agent-Token`。

### 路由模块清单

| 模块文件 | 路由前缀 | 核心能力 |
| --- | --- | --- |
| `main.py` | `/api/health`, `/api/ready`, `/metrics` | 存活检查、Redis/DB 就绪探针、Prometheus 指标 |
| `auth.py` | `/api/auth` | 邮箱验证码发送、注册、密码/验证码登录、Refresh 刷新、登出、重置密码 |
| `users.py` | `/api/users` | 个人资料、积分余额与流水、兑换码、密码与人设/头像、会话设备管理、用户反馈 |
| `conversations.py` | `/api/conversations` | 会话列表、创建、重命名、归档、删除、消息历史 |
| `chat.py` | `/api/conversations`, `/api/events` | 对话票据签发、消息发送/重新生成/编辑、SSE 流式输出与实时事件订阅 |
| `files.py` | `/api/files` | COS 预签名直传、上传确认、文件列表、下载、文本内容读写与删除 |
| `library.py` | `/api/library` | 知识库文档管理与索引状态 |
| `memory.py` | `/api/memory` | 长期记忆列表、审批、编辑与删除 |
| `search.py` | `/api/search` | `/api/search/unified` 跨对话/文件/记忆统一检索 |
| `skills.py` | `/api/skills` | 技能列表、创建/更新/删除、GitHub 预览与安装同步、待审批技能 |
| `schedules.py` | `/api/schedules` | 定时任务 CRUD、Cron 预览、立即执行、取消运行与待审批提案 |
| `posts.py` | `/api/posts` | 动态帖发布、点赞、收藏、评论与基于帖子的讨论会话 |
| `mcp.py` | `/api/mcp` | 内部 MCP 工具端点（供 `agent-worker` 调用） |
| `internal_files.py` | `/api/internal/files` | 内部文件读取与解析服务 |
| `agent.py` | `/api/agent` | 查询 `/api/agent/status` 与 `/api/agent/topology` |
| `desktop.py` | `/api/desktop` | 桌面端策略信封下发、OpenAI 兼容代理与 Work 同步接口 |
| `admin.py` | `/api/admin` | 管理后台总览、分析、实时监控、会话强制停止、用户与会话管理、审计日志校验与导出 |
| `admin_membership.py` | `/api/admin` | 邀请码 CRUD、核销记录、调整用户会员与积分 |
| `admin_dashboards.py` | `/api/admin/dashboards` | 定时任务、HTTP 工具与 Web 搜索分析面板 |
| `admin_ops.py` | `/api/admin/ops` | 系统巡检、SLO、告警规则 CRUD 与测试、RAG 健康检查/回填/DLQ 重放 |
| `admin_quant.py` | `/api/admin/quant` | 模型/工具指标、留存、反馈处理、定价配置、离线 Eval 报告与触发 |

---

## 2. Agent Control API（`:8642`）

位于 [agent/app/api.py](file:///d:/.Resource/Project/Whitz/agent/app/api.py)，供 `server` 内部调用（除 `/health` 与 `/metrics` 外均校验 `X-Agent-Token`）：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /health` | Agent 服务健康检查 |
| `GET /metrics` | Prometheus 指标输出 |
| `GET /v1/graph/topology` | 获取 LangGraph 图拓扑结构 |
| `POST /v1/runs` | 创建并入队新的 Agent 运行任务（返回 `201` 与 `run_id`） |
| `GET /v1/runs/{run_id}` | 查询运行状态与元数据 |
| `POST /v1/runs/{run_id}/resume` | 恢复处于中断/等待审批状态的运行 |
| `POST /v1/runs/{run_id}/cancel` | 取消正在运行的任务 |
| `GET /v1/runs/{run_id}/events` | 订阅单次运行的 SSE 事件流 |
| `DELETE /v1/threads/{thread_id}` | 清理指定会话线程的 Checkpoint 状态 |
