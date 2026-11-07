import re
from typing import Literal

from pydantic import BaseModel, Field

from app.config.settings import Settings

DetailMode = Literal["full", "redacted", "off"]
_SECRET_KEYS = {"api_key", "apikey", "password", "secret", "token", "authorization"}
_SECRET_VALUE = re.compile(r"sk-[A-Za-z0-9]{8,}")


class ModelLogPolicy(BaseModel):
    detail: DetailMode
    sample_rate: float = Field(ge=0, le=1)
    retention_days: int = Field(ge=1)
    expose_snapshots: bool


def log_policy(settings: Settings) -> ModelLogPolicy:
    requested = settings.model_log_detail.strip().lower()
    if requested == "full" or (requested == "" and settings.app_env == "development"):
        detail: DetailMode = "full"
    elif requested == "off":
        detail = "off"
    else:
        detail = "redacted"
    if settings.model_log_sample_rate is None:
        sample_rate = 1.0 if settings.app_env == "development" else 0.0
    else:
        sample_rate = settings.model_log_sample_rate
    expose = settings.app_env == "development" or settings.model_log_expose_snapshots
    return ModelLogPolicy(
        detail=detail,
        sample_rate=sample_rate,
        retention_days=settings.model_log_retention_days,
        expose_snapshots=expose,
    )


def redact_secrets(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            redacted[str(key)] = "[redacted]" if normalized in _SECRET_KEYS else redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[redacted]", value)
    return value


def omit_text(value: object) -> object:
    """保留结构，去掉可能含个人内容的正文。"""
    if isinstance(value, dict):
        hidden: dict[str, object] = {}
        for key, item in value.items():
            if str(key) in {"content", "prompt", "response_text"} and isinstance(item, str):
                hidden[str(key)] = f"[omitted:{len(item)}]"
            else:
                hidden[str(key)] = omit_text(item)
        return hidden
    if isinstance(value, list):
        return [omit_text(item) for item in value]
    return value
