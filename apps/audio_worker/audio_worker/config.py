from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKER_ROOT = Path(__file__).resolve().parents[1]


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WORKER_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8100
    # stub | sensevoice | auto
    asr_backend: str = "stub"
    # 仅 stub。本地 CosyVoice 已移除，云端合成由请求里的 provider 决定。
    tts_backend: str = "stub"
    asr_model_name: str = "iic/SenseVoiceSmall"
    model_dir: Path = Field(default=WORKER_ROOT / "models")
    output_dir: Path = Field(default=WORKER_ROOT / "outputs")
    max_queue_size: int = Field(default=8, ge=1)
    fish_api_key: str = ""
    volcengine_api_key: str = ""
    dashscope_api_key: str = ""
    dashscope_workspace_id: str = ""


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
