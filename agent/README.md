# Whitz Agent

基于 LangGraph 的独立多智能体运行时，包含 Control API 与 ARQ Worker。

## 目录结构

- `app/api.py`：Control API（`/v1/runs` 等，`X-Agent-Token` 鉴权）
- `app/worker.py`：ARQ Worker
- `app/runner.py`：运行编排
- `app/graph/`：状态图构建、子图、拓扑
- `app/tools/`：内置工具、MCP 客户端、代码沙箱（docker / e2b）
- `app/rag/`：混合检索、查询改写、引用
- `app/memory/`：长期记忆存储
- `evals/dataset.json`：离线评估数据集
- `tests/`：pytest 测试

## 本地开发

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

通过 `AGENT_ROLE=api|worker` 选择运行角色，参见 `docker-compose.yml`。

## 测试

```bash
.venv/Scripts/python -m pytest -q
```
