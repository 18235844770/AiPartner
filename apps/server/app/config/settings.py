from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=SERVER_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    database_url: str = "postgresql+asyncpg://companion:companion@127.0.0.1:5432/companion"
    redis_url: str = "redis://127.0.0.1:6379/0"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = Field(default=60, gt=0)
    deepseek_max_retries: int = Field(default=1, ge=0)
    embedding_model_name: str = Field(default="BAAI/bge-m3", min_length=1, max_length=64)
    model_log_detail: str = ""
    model_log_sample_rate: float | None = Field(default=None, ge=0, le=1)
    model_log_retention_days: int = Field(default=14, ge=1)
    model_log_expose_snapshots: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
