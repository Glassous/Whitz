# 环境变量参考

所有服务端与运行时配置均集中定义在根目录 [`.env.example`](file:///d:/.Resource/Project/Whitz/.env.example)。部署前请复制为 `.env` 并按环境要求填写。

## 1. 数据库与基础密钥

| 变量名 | 默认值 / 示例 | 说明 |
| --- | --- | --- |
| `POSTGRES_USER` | `whitz` | PostgreSQL 用户名 |
| `POSTGRES_PASSWORD` | `whitz_dev_password` | PostgreSQL 密码（生产环境必须修改） |
| `POSTGRES_DB` | `whitz` | PostgreSQL 数据库名 |
| `JWT_SECRET` | `please-change-me` | JWT 签名密钥，建议 `openssl rand -hex 32` |
| `AGENT_INTERNAL_TOKEN` | `please-change-me` | `server` 与 `agent-api` 间的内部鉴权 Token（`X-Agent-Token`） |
| `APP_DATA_DIR` | `/app-data` | 头像、工作区临时产物等共享卷路径 |

## 2. LLM 与多模型路由

| 变量名 | 默认值 / 示例 | 说明 |
| --- | --- | --- |
| `LLM_BASE_URL` | `https://your-endpoint.example.com/v1` | 主模型 OpenAI 兼容接口地址 |
| `LLM_API_KEY` | — | 主模型 API Key |
| `LLM_MODEL` | — | 主模型名称 |
| `LLM_SUPPORTS_VISION` | `true` | 主模型是否支持原生多模态图片输入 |
| `LLM_FAST_*` | 空（回退主模型） | 轻量任务模型（`BASE_URL` / `API_KEY` / `MODEL`） |
| `LLM_REASONING_*` | 空（回退主模型） | 深度推理模型（`BASE_URL` / `API_KEY` / `MODEL`） |
| `LLM_VISION_*` | 空（回退主模型） | 视觉理解模型（`BASE_URL` / `API_KEY` / `MODEL`） |
| `LLM_THINKING_MODE` | `auto` | 思考模式：`auto` / `enabled` / `disabled` |
| `LLM_THINKING_PARAM_STYLE` | `auto` | 思考参数协议：`auto` / `deepseek` / `qwen` / `openai` / `none` |
| `LLM_ADAPTIVE_PROBE_ENABLED` | `true` | 是否启用模型能力自适应探测 |

## 3. Embedding、Rerank 与深度 RAG

| 变量名 | 默认值 / 示例 | 说明 |
| --- | --- | --- |
| `EMBEDDING_BASE_URL` | `https://api.siliconflow.cn/v1` | OpenAI 兼容 `/v1/embeddings` 地址；留空则平滑降级为 `pg_trgm` + FTS |
| `EMBEDDING_API_KEY` | — | Embedding API Key |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding 模型名 |
| `EMBEDDING_DIMENSIONS` | `1536` | pgvector 列维度 |
| `EMBEDDING_BATCH_SIZE` | `10` | 单次批量向量化上限 |
| `EMBEDDING_CACHE_TTL_SECONDS` | `86400` | Redis 向量缓存过期时间（秒） |
| `RERANK_BASE_URL` / `KEY` / `MODEL` | 空（跳过重排） | Stage-2 Reranker 配置（兼容 DashScope / Jina / SiliconFlow） |
| `RERANK_TOP_N` | `8` | 重排返回条数 |
| `RAG_IMAGE_INDEXING_ENABLED` | `true` | 图片视觉摘要入库开关 |
| `RAG_PREFETCH_ENABLED` | `true` | 前置主动预召回开关 |
| `RAG_QUERY_REWRITE_ENABLED` | `true` | 查询改写开关 |
| `RAG_MEMORY_CONSOLIDATION_ENABLED` | `true` | 记忆语义巩固开关 |

## 4. 沙箱、可观测性与搜索

| 变量名 | 默认值 / 示例 | 说明 |
| --- | --- | --- |
| `SANDBOX_MODE` | `disabled` | 代码执行沙箱：`disabled` / `docker` / `e2b` |
| `E2B_API_KEY` | 空 | E2B 云端沙箱密钥 |
| `LANGSMITH_TRACING` | `false` | 是否开启 LangSmith 链路追踪 |
| `LANGSMITH_API_KEY` / `PROJECT` / `ENDPOINT` | — | LangSmith 配置 |
| `SEARCH_API_KEY` / `BOCHA_API_KEY` | 空 | Tavily 与博查搜索密钥；均留空时回退内置 DuckDuckGo |

## 5. 运维、认证、限流与积分

| 变量名 | 默认值 | 说明 |
| --- | --- | --- |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | `admin@example.com` | 首个管理员账号（启动时自动创建） |
| `APP_ENV` | `production` | 运行环境标识 |
| `AUTH_COOKIE_SECURE` | `false` | HTTPS 部署后应设为 `true` |
| `AUTH_COOKIE_SAMESITE` | `lax` | Refresh Cookie SameSite 策略 |
| `ALLOWED_HOSTS` | `*` | TrustedHost 白名单，逗号分隔 |
| `CORS_ORIGINS` | `http://localhost:5173` | 允许的 Web 来源 |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | 反向代理可信 IP |
| `JWT_ACCESS_TTL_MINUTES` / `JWT_REFRESH_TTL_DAYS` | `15` / `15` | Access / Refresh Token 有效期 |
| `MAX_CONCURRENT_RUNS` / `_PER_USER` | `4` / `2` | 全局与单用户并发运行上限 |
| `MAX_SSE_STREAMS` / `_PER_USER` | `32` / `8` | 并发 SSE 订阅上限 |
| `RUN_MAX_SECONDS` | `1200` | 单次 Agent 运行最大超时（秒） |
| `CHAT_RATE_PER_MINUTE` | `30` | 对话限流（次/分钟） |
| `TOKENS_PER_CREDIT` | `5000` | 1 积分对应的 Token 数 |
| `MEMBERSHIP_DEFAULT_DAYS` | `30` | 默认会员有效期（天） |
| `STRICT_TICKET_IP` | `false` | 对话票据是否绑定客户端 IP |
| `AUDIT_ENABLED` | `true` | 是否记录审计日志 |

## 6. 邮件（SMTP）、对象存储（COS）与桌面端（Desktop）

- **SMTP**：`SMTP_HOST`（默认 `smtp.qq.com`）、`SMTP_PORT`（`465`）、`SMTP_USERNAME`、`SMTP_PASSWORD`、`SMTP_FROM_EMAIL`、`SMTP_FROM_NAME`、`SMTP_USE_SSL`、`SMTP_USE_TLS`、`EMAIL_CODE_*`。
- **腾讯云 COS & 多模态附件**：`COS_SECRET_ID`、`COS_SECRET_KEY`、`COS_BUCKET`、`COS_REGION`、`COS_PUBLIC_HOST`、`COS_KEY_PREFIX`、`COS_USE_STS`、`LLM_IMAGE_DELIVERY_MODE`（`url_first` / `base64` / `url_only`）、`LLM_NATIVE_PDF_MODE`、`FILE_MAX_SIZE_MB`（`20`）、`MAX_FILES_PER_CONVERSATION`（`20`）。
- **内部通信与桌面端**：`INTERNAL_MCP_BASE_URL`（默认 `http://server:8000`）、`DESKTOP_ORIGINS`（`app://whitz,http://localhost:5174`）、`DESKTOP_WORK_MODE_ENABLED`、`DESKTOP_MIN_APP_VERSION`、`DESKTOP_POLICY_PRIVATE_KEY`、`DESKTOP_LLM_*`。
