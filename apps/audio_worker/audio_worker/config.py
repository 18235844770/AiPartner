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
    # stub | cosyvoice3 | auto
    tts_backend: str = "stub"
    asr_model_name: str = "iic/SenseVoiceSmall"
    tts_model_name: str = "Fun-CosyVoice3-0.5B-2512"
    model_dir: Path = Field(default=WORKER_ROOT / "models")
    output_dir: Path = Field(default=WORKER_ROOT / "outputs")
    # CosyVoice 官方仓库本地路径（含 cosyvoice/ 与 third_party/Matcha-TTS）
    cosyvoice_repo: Path = Field(default=WORKER_ROOT / "vendor" / "CosyVoice")
    # 可选默认参考音频；空则使用仓库 asset/zero_shot_prompt.wav
    tts_default_prompt_wav: Path | None = None
    tts_fp16: bool = True
    max_queue_size: int = Field(default=8, ge=1)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
