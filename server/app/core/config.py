from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://whitz:whitz_dev_password@localhost:5432/whitz"
    jwt_secret: str = "dev-secret-change-me"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7

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