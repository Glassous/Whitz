from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://whitz:whitz_dev_password@localhost:5432/whitz"
    jwt_secret: str = "dev-secret-change-me"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 15
    auth_refresh_grace_seconds: int = 30
    auth_cookie_enabled: bool = True
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_path: str = "/api/auth"
    auth_cookie_name: str = "whitz_refresh"

    redis_url: str = "redis://localhost:6379/0"
    redis_max_connections: int = 64
    redis_socket_timeout: float = 3.0

    max_concurrent_runs: int = 4
    max_concurrent_runs_per_user: int = 2
    max_sse_streams: int = 32
    max_sse_streams_per_user: int = 8
    run_max_seconds: int = 1200
    chat_rate_per_minute: int = 30
    tokens_per_credit: int = 5000
    membership_default_days: int = 30
    strict_ticket_ip: bool = False
    forwarded_allow_ips: str = "127.0.0.1"
    allowed_hosts: str = "*"
    audit_enabled: bool = True

    scheduler_enabled: bool = True
    scheduler_poll_interval_seconds: float = 10.0
    scheduler_batch_size: int = 20
    scheduler_max_consecutive_failures: int = 5

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_supports_vision: bool = True
    llm_fast_base_url: str = ""
    llm_fast_api_key: str = ""
    llm_fast_model: str = ""
    llm_reasoning_base_url: str = ""
    llm_reasoning_api_key: str = ""
    llm_reasoning_model: str = ""
    llm_vision_base_url: str = ""
    llm_vision_api_key: str = ""
    llm_vision_model: str = ""

    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 1536
    embedding_batch_size: int = 10
    embedding_cache_ttl_seconds: int = 86400
    embedding_timeout_seconds: float = 30.0

    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    rerank_top_n: int = 8
    rerank_timeout_seconds: float = 15.0

    # Deep RAG feature flags
    rag_image_indexing_enabled: bool = True
    rag_doc_summary_llm_enabled: bool = True

    search_api_key: str = ""
    bocha_api_key: str = ""

    agent_base_url: str = "http://localhost:8642"
    agent_internal_token: str = "dev-agent-token"
    app_data_dir: str = "./.whitz-data"
    builtin_skills_dir: str = ""

    sandbox_mode: str = "disabled"
    e2b_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "whitz-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # Built-in skills that depend on disabled/unavailable host tools can be filtered
    # via comma-separated allowlist / denylist names.
    skills_builtin_allowlist: str = ""
    skills_builtin_denylist: str = ""

    admin_email: str = ""
    admin_password: str = ""
    cors_origins: str = "http://localhost:5173"

    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Whitz"
    smtp_use_ssl: bool = True
    smtp_use_tls: bool = False
    smtp_timeout_seconds: float = 15.0

    email_code_ttl_seconds: int = 600
    email_code_cooldown_seconds: int = 60
    email_code_max_attempts: int = 5

    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_bucket: str = ""
    cos_region: str = ""
    cos_public_host: str = ""
    cos_key_prefix: str = "whitz/uploads"
    cos_use_sts: bool = False
    cos_sts_duration_seconds: int = 900
    cos_upload_expires_seconds: int = 600
    cos_download_expires_seconds: int = 300
    cos_image_thumb_query: str = ""
    file_max_size_mb: int = 20
    max_files_per_conversation: int = 20
    pending_file_ttl_seconds: int = 1800

    internal_mcp_base_url: str = "http://server:8000"

    # ===== 桌面端 =====
    desktop_origins: str = "app://whitz,http://localhost:5174"
    desktop_work_mode_enabled: bool = True
    desktop_work_disabled_reason: str = ""
    desktop_min_app_version: str = "0.1.0"
    desktop_latest_app_version: str = ""
    desktop_policy_ttl_minutes: int = 360
    # Ed25519 私钥：base64 原始 32 字节种子，或 PEM。留空则不签名（仅开发环境）
    desktop_policy_private_key: str = ""
    desktop_policy_key_id: str = "desktop-1"
    desktop_llm_model_alias: str = "whitz-default"
    # 代理转发给上游的真实模型名；留空则复用 LLM_MODEL
    desktop_llm_upstream_model: str = ""
    desktop_llm_max_tokens: int = 8192
    desktop_llm_base_url: str = ""
    desktop_llm_request_timeout_seconds: float = 300.0

    @property
    def cos_configured(self) -> bool:
        return bool(
            self.cos_secret_id.strip()
            and self.cos_secret_key.strip()
            and self.cos_bucket.strip()
            and self.cos_region.strip()
        )

    @property
    def max_file_size_bytes(self) -> int:
        return max(1, int(self.file_max_size_mb)) * 1024 * 1024

    @property
    def app_data_path(self) -> Path:
        """APP_DATA_DIR 解析后的路径；空值（.env 里写了 APP_DATA_DIR=）回退到默认目录。"""
        raw = (self.app_data_dir or "").strip()
        return Path(raw or "./.whitz-data")


@lru_cache
def get_settings() -> Settings:
    return Settings()