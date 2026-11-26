# Whitz Server

多租户后端控制面（FastAPI + SQLAlchemy Async + PostgreSQL/pgvector + Redis）。

## 目录结构

- `app/main.py`：应用工厂、中间件、生命周期（调度器、RAG 任务、告警评估器）
- `app/api/routes/`：REST / SSE 路由（详见 [docs/api.md](../docs/api.md)）
- `app/services/`：业务服务（对话流、文件、COS、记忆、调度、会员、审计等）
- `app/core/`：配置、安全、限流、Redis、指标
- `app/db/`：ORM 模型与会话
- `tests/`：pytest 测试

## 本地开发

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

环境变量见 [docs/environment.md](../docs/environment.md)。

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

测试连接 `localhost:5434` 的 PostgreSQL（`docker compose up -d postgres`），`conftest.py` 会自动创建 `whitz_test` 库；Redis 使用内存实现（`memory://`）。纯逻辑测试（如 `test_pure_audit_pricing_reactions.py`、`test_event_normalizer_unit.py`、`test_ratelimit_unit.py`）不访问数据库。详见 [docs/testing.md](../docs/testing.md)。
