# API 接口参考

本文档基于 `server` 与 `agent` 实际挂载的 FastAPI 路由整理（共 188 个 Server 端点与 9 个 Agent 业务端点）。开发环境下可通过 `/docs` 访问交互式 Swagger UI。

## 鉴权方式

- **用户态接口**：`Authorization: Bearer <access_token>`，配合 `/api/auth/refresh` 使用 HttpOnly Refresh Cookie 续期。
- **管理员接口**：需具备 `admin` 角色（`require_admin`）。
- **内部服务接口**：`/api/internal/*` 与 Agent Control API 使用 `X-Agent-Token` 请求头校验。
- **桌面端 OpenAI 代理**：`/api/desktop/llm/v1/*` 使用 `/api/desktop/llm-key` 签发的桌面端密钥。

---

## 1. Server 控制面 API（`:8000`）

### 1.1 系统探针与指标

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 存活检查 |
| `GET` | `/api/ready` | Redis 与 PostgreSQL 就绪探针 |
| `GET` | `/metrics` | Prometheus 指标导出（不计入 OpenAPI） |

### 1.2 认证与用户（`auth`, `users`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/auth/email-code` | 发送邮箱验证码 |
| `POST` | `/api/auth/register` | 邮箱验证码注册 |
| `POST` | `/api/auth/login` | 密码登录 |
| `POST` | `/api/auth/login/code` | 邮箱验证码登录 |
| `POST` | `/api/auth/refresh` | 刷新 Access Token（支持 Cookie） |
| `POST` | `/api/auth/logout` | 登出并撤销当前会话 |
| `POST` | `/api/auth/reset-password` | 验证码重置密码 |
| `GET` / `PATCH` | `/api/users/me` | 获取/更新个人资料 |
| `PATCH` | `/api/users/me/profile-context` | 更新用户画像上下文 |
| `PUT` | `/api/users/me/password` | 修改密码（保留当前设备，撤销其他设备） |
| `PUT` | `/api/users/me/persona` | 更新系统人设 |
| `PUT` / `DELETE` | `/api/users/me/avatar` | 上传/删除用户头像 |
| `PATCH` | `/api/users/me/assistant` | 更新助手名称等配置 |
| `PUT` / `DELETE` | `/api/users/me/assistant/avatar` | 上传/删除助手头像 |
| `GET` | `/api/users/{user_id}/avatar` | 获取用户头像 |
| `GET` | `/api/users/{user_id}/assistant-avatar` | 获取助手头像 |
| `GET` | `/api/users/me/credits` | 查询会员档位与积分额度 |
| `GET` | `/api/users/me/credits/ledger` | 查询积分流水 |
| `POST` | `/api/users/me/redeem` | 核销邀请码 |
| `GET` / `DELETE` | `/api/users/me/sessions` | 列出/撤销全部其他设备会话 |
| `DELETE` | `/api/users/me/sessions/{session_id}` | 撤销指定设备会话 |
| `PUT` | `/api/users/me/ai-reactions` | 开关 AI 互动回应 |
| `PUT` | `/api/users/me/ai-posts` | 开关 AI 主动发帖 |
| `GET` / `POST` | `/api/users/me/feedback` | 查询/提交用户反馈 |

### 1.3 对话、流式输出与实时事件（`conversations`, `chat`, `events`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` / `POST` | `/api/conversations` | 会话列表 / 创建会话 |
| `GET` | `/api/conversations/main` | 获取或初始化唯一主聊 |
| `GET` | `/api/conversations/search` | 搜索会话 |
| `GET` / `PATCH` / `DELETE` | `/api/conversations/{conversation_id}` | 获取详情 / 重命名 / 删除会话 |
| `GET` | `/api/conversations/{conversation_id}/context-state` | 获取上下文与工作态摘要 |
| `PATCH` | `/api/conversations/{conversation_id}/working-state` | 更新 L1 工作态 |
| `POST` | `/api/conversations/{conversation_id}/archive-episode` | 手动归档 L2 情景卡片 |
| `POST` | `/api/conversations/{conversation_id}/title/generate` | 自动生成会话标题 |
| `POST` | `/api/conversations/{conversation_id}/tickets` | 签发一次性对话票据 |
| `POST` | `/api/conversations/{conversation_id}/messages` | 发送消息并开启 SSE 流 |
| `POST` | `/api/conversations/{conversation_id}/messages/{message_id}/regenerate` | 重新生成回复 |
| `POST` | `/api/conversations/{conversation_id}/messages/{message_id}/edit` | 编辑消息并重发 |
| `POST` / `DELETE` | `/api/conversations/{conversation_id}/messages/{message_id}/reactions` | 添加/移除消息表情反馈 |
| `GET` | `/api/conversations/{conversation_id}/runs/{run_id}/events` | 断线重连拉取/订阅运行事件 |
| `POST` | `/api/conversations/{conversation_id}/stop` | 停止当前运行 |
| `POST` | `/api/conversations/{conversation_id}/approval` | 提交工具审批结果 |
| `POST` | `/api/conversations/{conversation_id}/clarify` | 提交追问澄清结果 |
| `GET` | `/api/events/stream` | 全局用户级实时 SSE 事件流 |

### 1.4 文件工作区、资料库与统一检索（`files`, `library`, `search`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/conversations/{conversation_id}/files` | 列出会话文件 |
| `POST` | `/api/conversations/{conversation_id}/files/presign` | 签发 COS 预签名上传地址 |
| `POST` | `/api/conversations/{conversation_id}/files/text` | 直接创建文本文件 |
| `POST` | `/api/conversations/{conversation_id}/files/{file_id}/complete` | 确认上传完成并触发索引 |
| `PATCH` / `DELETE` | `/api/conversations/{conversation_id}/files/{file_id}` | 重命名 / 删除文件 |
| `PUT` | `/api/conversations/{conversation_id}/files/{file_id}/content` | 更新文本文件内容 |
| `GET` | `/api/conversations/{conversation_id}/files/{file_id}/download-url` | 获取下载链接 |
| `GET` | `/api/conversations/{conversation_id}/files/{file_id}/preview-content` | 获取预览内容 |
| `POST` | `/api/conversations/{conversation_id}/files/attach` | 挂载全局资料库文件到会话 |
| `GET` | `/api/library/files` | 列出全局资料库文件 |
| `POST` | `/api/library/files/presign` | 资料库文件预签名上传 |
| `POST` | `/api/library/files/{file_id}/complete` | 确认资料库上传完成 |
| `PATCH` / `DELETE` | `/api/library/files/{file_id}` | 更新元数据 / 删除资料库文件 |
| `PUT` | `/api/library/files/{file_id}/content` | 更新资料库文本内容 |
| `GET` | `/api/library/files/{file_id}/download-url` | 获取资料库下载链接 |
| `GET` | `/api/library/files/{file_id}/preview-content` | 获取资料库预览内容 |
| `POST` | `/api/library/files/{file_id}/reindex` | 重建文件向量索引 |
| `GET` | `/api/library/search` | 资料库全文/语义检索 |
| `GET` | `/api/search/unified` | 跨对话/资料库/记忆统一混合检索 |

### 1.5 长期记忆、技能、定时任务与动态帖（`memory`, `skills`, `schedules`, `posts`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` / `DELETE` | `/api/users/me/memory` | 记忆总览 / 清空全部记忆 |
| `PUT` | `/api/users/me/memory/settings` | 更新记忆开关与审批设置 |
| `POST` | `/api/users/me/memory/search` | 语义检索记忆 |
| `GET` | `/api/users/me/memory/pending` | 待审批记忆提案列表 |
| `POST` | `/api/users/me/memory/pending/{pending_id}` | 批准/拒绝记忆提案 |
| `POST` | `/api/users/me/memory/collections` | 创建记忆集合 |
| `PATCH` / `DELETE` | `/api/users/me/memory/collections/{collection_id}` | 更新/删除记忆集合 |
| `POST` | `/api/users/me/memory/entries` | 创建记忆条目 |
| `PATCH` / `DELETE` | `/api/users/me/memory/entries/{entry_id}` | 更新/删除记忆条目 |
| `GET` / `POST` | `/api/skills` | 技能列表 / 创建技能 |
| `PUT` / `PATCH` / `DELETE` | `/api/skills/{name}` | 更新 / 启停 / 删除技能 |
| `POST` | `/api/skills/preview-github` | 预览 GitHub 技能仓库 |
| `POST` | `/api/skills/install-github` | 从 GitHub 安装技能 |
| `POST` | `/api/skills/{name}/sync-github` | 同步 GitHub 技能 |
| `GET` | `/api/skills/pending` | 待审批技能列表 |
| `POST` | `/api/skills/pending/{pending_id}` | 审批技能提案 |
| `GET` / `POST` | `/api/schedules` | 定时任务总览 / 创建 |
| `POST` | `/api/schedules/preview` | 预览 Cron 下次触发时间 |
| `GET` / `PATCH` / `DELETE` | `/api/schedules/{task_id}` | 任务详情 / 更新 / 删除 |
| `POST` | `/api/schedules/{task_id}/run-now` | 立即触发一次执行 |
| `POST` | `/api/schedules/{task_id}/runs/{run_id}/cancel` | 取消运行中的调度记录 |
| `GET` | `/api/schedules/pending` | 待审批定时任务提案 |
| `POST` | `/api/schedules/pending/{proposal_id}` | 审批定时任务提案 |
| `GET` / `POST` | `/api/posts` | 动态帖列表 / 发帖 |
| `GET` | `/api/posts/quota` | 查询发帖配额 |
| `GET` / `DELETE` | `/api/posts/{post_id}` | 获取 / 删除动态帖 |
| `POST` | `/api/posts/{post_id}/like` | 点赞切换 |
| `POST` | `/api/posts/{post_id}/bookmark` | 收藏切换 |
| `POST` | `/api/posts/{post_id}/comments` | 添加评论 |
| `DELETE` | `/api/posts/{post_id}/comments/{comment_id}` | 删除评论 |
| `POST` | `/api/posts/{post_id}/discuss` | 转入对话讨论 |

### 1.6 Agent 状态、桌面端与内部接口（`agent`, `desktop`, `internal-files`, `internal-mcp`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/agent/status` | 查询 Agent 就绪状态与模型配置 |
| `GET` | `/api/agent/topology` | 获取 LangGraph 节点拓扑（不可达时回退默认拓扑） |
| `GET` | `/api/desktop/policy` | 获取桌面端 Work 模式策略信封 |
| `GET` | `/api/desktop/policy/public-key` | 获取 Ed25519 策略验签公钥 |
| `POST` / `DELETE` | `/api/desktop/llm-key` | 签发 / 撤销桌面端内置模型密钥 |
| `GET` | `/api/desktop/llm/v1/models` | 桌面端 OpenAI 兼容模型列表 |
| `POST` | `/api/desktop/llm/v1/chat/completions` | 桌面端 OpenAI 兼容推理代理 |
| `POST` | `/api/internal/files/prepare-turn` | 为轮次准备多模态/文本附件 |
| `GET` | `/api/internal/files/sandbox-inputs` | 获取沙箱输入文件列表 |
| `POST` | `/api/internal/files/sandbox-output` | 回存沙箱产物文件 |
| `GET` | `/api/internal/files/{file_id}/media` | 内部媒体文件兜底读取 |
| `GET` / `POST` / `DELETE` | `/api/internal/mcp/files` | 内部 MCP 文件工具 |
| `GET` / `POST` / `DELETE` | `/api/internal/mcp/schedules` | 内部 MCP 定时任务工具 |
| `GET` / `POST` / `DELETE` | `/api/internal/mcp/skills` | 内部 MCP 技能工具 |

### 1.7 管理后台（`admin`, `admin-dashboards`, `admin-ops`, `admin-quant`）

- **`/api/admin`**：`overview`、`analytics`、`monitor`、`conversations/{conversation_id}/stop`、`users`（列表、详情、`ledger`、`sessions`、会员与积分调整）、`invite-codes`（CRUD 与核销记录）、`audit-logs`（列表、`verify` 哈希链校验、`analytics`、`trace/{trace_id}`、`export`）。
- **`/api/admin/dashboards`**：`schedules`、`http-tools`、`web-search`、`export`。
- **`/api/admin/ops`**：`inspection`、`slo`、`alerts`（规则 CRUD、测试 Webhook、确认、评估）、`rag/health`、`rag/backfill`、`rag/dlq`（查看、重放、清空）。
- **`/api/admin/quant`**：`summary`、`models-tools`、`retention`、`feedback`、`pricing`（查询/更新/重算）、`export`、`evals`（列表、上报、触发评估）。

---

## 2. Agent Control API（`:8642`）

位于 [agent/app/api.py](file:///d:/.Resource/Project/Whitz/agent/app/api.py)，除 `/health` 与 `/metrics` 外均校验 `X-Agent-Token`：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | Agent 服务健康与沙箱模式探针 |
| `GET` | `/metrics` | Prometheus 指标导出 |
| `GET` | `/v1/graph/topology` | 获取 LangGraph 图拓扑结构 |
| `POST` | `/v1/runs` | 创建并入队运行任务（`201` 返回 `run_id`） |
| `GET` | `/v1/runs/{run_id}` | 查询运行状态与元数据 |
| `POST` | `/v1/runs/{run_id}/resume` | 恢复处于中断/等待审批状态的运行 |
| `POST` | `/v1/runs/{run_id}/cancel` | 取消运行任务 |
| `GET` | `/v1/runs/{run_id}/events` | 订阅单次运行的 SSE 事件流 |
| `DELETE` | `/v1/threads/{thread_id}` | 清理指定线程的 Checkpoint 状态 |
