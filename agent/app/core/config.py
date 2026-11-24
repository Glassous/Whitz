from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    agent_port: int = 8642
    agent_internal_token: str = "dev-agent-token"

    database_url: str = "postgresql://whitz:whitz_dev_password@localhost:5432/whitz"
    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 64
    redis_socket_timeout: float = 5.0

    internal_mcp_base_url: str = "http://server:8000"

    # Primary LLM (OpenAI-compatible)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_supports_vision: bool = True
    llm_timeout_seconds: float = 120.0

    # Optional task-routed LLMs
    llm_fast_base_url: str = ""
    llm_fast_api_key: str = ""
    llm_fast_model: str = ""

    llm_reasoning_base_url: str = ""
    llm_reasoning_api_key: str = ""
    llm_reasoning_model: str = ""

    llm_vision_base_url: str = ""
    llm_vision_api_key: str = ""
    llm_vision_model: str = ""

    # Autonomous thinking-mode control
    llm_thinking_mode: Literal["auto", "enabled", "disabled"] = "auto"
    llm_thinking_param_style: Literal["auto", "deepseek", "qwen", "openai", "none"] = "auto"
    llm_adaptive_probe_enabled: bool = True

    # Optional Embeddings (OpenAI-compatible /v1/embeddings -> 1536 dims)
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 10
    embedding_cache_ttl_seconds: int = 86400
    embedding_timeout_seconds: float = 30.0

    # Optional Stage-2 Reranker (DashScope native & OpenAI/Jina/SiliconFlow compatible)
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    rerank_top_n: int = 8
    rerank_timeout_seconds: float = 15.0

    # Deep RAG (Dual-Loop Proactive Prefetch + Agentic Corrective RAG)
    rag_prefetch_enabled: bool = True
    rag_prefetch_max_tokens: int = 3000
    rag_query_rewrite_enabled: bool = True
    rag_memory_consolidation_enabled: bool = True

    # Circuit breaker
    model_cb_failure_threshold: int = 3
    model_cb_cooldown_seconds: int = 60

    # Sandbox execution
    sandbox_mode: Literal["docker", "e2b", "disabled"] = "disabled"
    sandbox_docker_image: str = "python:3.12-alpine"
    sandbox_timeout_seconds: int = 30
    e2b_api_key: str = ""

    # Search (Tavily + Bocha AI)
    search_api_key: str = ""
    bocha_api_key: str = ""
    bocha_search_url: str = "https://api.bochaai.com/v1/web-search"

    # Run limits & worker settings
    run_max_seconds: int = 1200
    worker_max_jobs: int = 8
    event_stream_ttl_seconds: int = 86400
    run_state_ttl_seconds: int = 86400
    stream_max_len: int = 10000

    # Context window & cost guardrails
    main_max_prompt_tokens: int = 24000
    side_max_prompt_tokens: int = 20000
    recent_verbatim_messages: int = 16

    # LangSmith
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "whitz-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    @property
    def psycopg_database_url(self) -> str:
        """Normalize SQLAlchemy-style Postgres URLs for psycopg3."""
        url = self.database_url.strip()
        if url.startswith("postgresql+asyncpg://"):
            return "postgresql://" + url[len("postgresql+asyncpg://") :]
        if url.startswith("postgresql+psycopg://"):
            return "postgresql://" + url[len("postgresql+psycopg://") :]
        if url.startswith("postgres://"):
            return "postgresql://" + url[len("postgres://") :]
        return url

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_base_url.strip()) and bool(self.embedding_model.strip())

    @property
    def rerank_configured(self) -> bool:
        return bool(self.rerank_base_url.strip()) and bool(self.rerank_model.strip())

    def configure_langsmith(self) -> None:
        if self.langsmith_tracing and self.langsmith_api_key.strip():
            os.environ.setdefault("LANGSMITH_TRACING", "true")
            os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
            os.environ.setdefault("LANGSMITH_API_KEY", self.langsmith_api_key.strip())
            os.environ.setdefault("LANGSMITH_PROJECT", self.langsmith_project.strip() or "whitz-agent")
            if self.langsmith_endpoint.strip():
                os.environ.setdefault("LANGSMITH_ENDPOINT", self.langsmith_endpoint.strip())


@lru_cache
def get_settings() -> AgentSettings:
    return AgentSettings()
