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
    chat_rate_per_minute: int = 30
    tokens_per_credit: int = 5000
    membership_default_days: int = 30
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
    file_max_size_mb: int = 20
    max_files_per_conversation: int = 20

    internal_mcp_base_url: str = "http://server:8000"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()