from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    event_store_backend: str = "memory"
    event_store_path: str = "data/runtime-events.sqlite3"
    model_provider: str = "none"
    model_base_url: str = ""
    model_api_key: str = ""
    model_name: str = ""
    model_timeout_seconds: float = Field(default=60, ge=1, le=600)
    model_retries: int = Field(default=1, ge=0, le=5)
    model_price_table: str = ""
    mcp_remote_url: str = ""
    mcp_remote_token: str = ""
    mcp_fallback_to_local: bool = False
    mcp_protocol: str = "rest"
    mcp_retries: int = Field(default=1, ge=0, le=5)
    mcp_server_token: str = ""
    mcp_allow_insecure: bool = False
    mcp_require_https: bool = False
    runtime_host: str = "127.0.0.1"
    runtime_port: int = Field(default=8001, ge=1, le=65535)
    multimodal_host: str = "127.0.0.1"
    multimodal_port: int = Field(default=8002, ge=1, le=65535)
    executor_concurrency: int = Field(default=1, ge=1, le=16)
    max_replans: int = Field(default=2, ge=0, le=5)
    approval_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    upload_dir: str = "data/uploads"
    max_upload_bytes: int = Field(default=5_242_880, ge=1, le=100_000_000)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
