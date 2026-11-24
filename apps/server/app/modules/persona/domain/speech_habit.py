"""口语语气词。按 MBTI 读取，不写入人格版本。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.modules.persona.domain.enums import MbtiType

_DATA = Path(__file__).resolve().parents[1] / "data" / "speech_habits.json"


class SpeechHabit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    particles: list[str] = Field(default_factory=list)
    habit: str = Field(min_length=1)


@lru_cache
def load_speech_habits() -> dict[str, SpeechHabit]:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("speech_habits 必须是对象")
    habits: dict[str, SpeechHabit] = {}
    for key, value in raw.items():
        MbtiType(key)
        habits[key] = SpeechHabit.model_validate(value)
    expected = {item.value for item in MbtiType}
    if set(habits) != expected:
        raise ValueError("speech_habits 必须覆盖六种 MBTI")
    return habits


def speech_habit_for(mbti_type: str) -> SpeechHabit | None:
    try:
        MbtiType(mbti_type)
    except ValueError:
        return None
    return load_speech_habits()[mbti_type]
