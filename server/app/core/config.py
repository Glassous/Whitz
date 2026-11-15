from functools import lru_cache

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
    redis_max_connections: int = 20
    redis_socket_timeout: float = 1.0

    max_concurrent_runs: int = 2
    max_concurrent_runs_per_user: int = 1
    max_sse_streams: int = 6
    max_sse_streams_per_user: int = 2
    run_max_seconds: int = 900
    daily_message_limit: int = 100
    daily_token_limit: int = 100000
    chat_rate_per_minute: int = 30
    strict_ticket_ip: bool = False
    forwarded_allow_ips: str = "127.0.0.1"
    allowed_hosts: str = "*"
    audit_enabled: bool = True

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    search_api_key: str = ""

    hermes_base_url: str = "http://localhost:8642"
    hermes_data_dir: str = "./.hermes-data"
    hermes_api_server_key: str = ""

    admin_email: str = ""
    admin_password: str = ""
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()