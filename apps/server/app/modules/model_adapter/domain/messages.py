from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class TextCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    model_name: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


def build_chat_payload(
    model_name: str,
    messages: list[ChatMessage],
    parameters: dict[str, object],
    *,
    json_object: bool,
    stream: bool,
) -> dict[str, object]:
    """只转发官方文档已说明的参数。型号来自配置，不在这里指定。"""
    payload: dict[str, object] = {
        "model": model_name,
        "messages": [item.model_dump() for item in messages],
        "stream": stream,
    }
    temperature = parameters.get("temperature")
    if isinstance(temperature, int | float) and not isinstance(temperature, bool) and 0 <= float(temperature) <= 2:
        payload["temperature"] = float(temperature)
    max_tokens = parameters.get("max_tokens")
    if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and 1 <= max_tokens <= 393216:
        payload["max_tokens"] = max_tokens
    thinking = parameters.get("thinking")
    if thinking in {"enabled", "disabled"}:
        payload["thinking"] = {"type": thinking}
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    return payload
