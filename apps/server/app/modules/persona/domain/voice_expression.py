"""人格语音表达倾向：数据化配置，写入 persona_versions.behavior_traits。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.modules.persona.domain.enums import MbtiType

_DATA = Path(__file__).resolve().parents[1] / "data" / "voice_expression_profiles.json"


class VoiceExpressionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expressiveness: float = Field(default=0.7, ge=0, le=1)
    speaking_pace: float = Field(default=1.0, gt=0.5, le=1.5)
    intonation_variation: float = Field(default=0.6, ge=0, le=1)
    emotional_expressiveness: float = Field(default=0.7, ge=0, le=1)
    pause_preference: float = Field(default=0.5, ge=0, le=1)
    directness: float = Field(default=0.5, ge=0, le=1)


@lru_cache
def load_voice_expression_profiles() -> dict[str, VoiceExpressionProfile]:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("voice_expression_profiles 必须是对象")
    profiles: dict[str, VoiceExpressionProfile] = {}
    for key, value in raw.items():
        MbtiType(key)
        profiles[key] = VoiceExpressionProfile.model_validate(value)
    expected = {item.value for item in MbtiType}
    if set(profiles) != expected:
        raise ValueError("voice_expression_profiles 必须覆盖六种 MBTI")
    return profiles


def default_voice_expression(mbti_type: str | MbtiType) -> VoiceExpressionProfile:
    key = mbti_type.value if isinstance(mbti_type, MbtiType) else mbti_type
    return load_voice_expression_profiles()[key].model_copy()


def resolve_voice_expression(
    behavior_traits: Mapping[str, object] | None,
    *,
    mbti_type: str | MbtiType | None = None,
) -> VoiceExpressionProfile:
    raw = None if behavior_traits is None else behavior_traits.get("voice_expression")
    if isinstance(raw, dict):
        try:
            return VoiceExpressionProfile.model_validate(raw)
        except Exception:
            pass
    if mbti_type is not None:
        try:
            return default_voice_expression(mbti_type)
        except Exception:
            return VoiceExpressionProfile()
    return VoiceExpressionProfile()
