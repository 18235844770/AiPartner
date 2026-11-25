"""可切换的云端音色目录。内容来自数据文件，不写进合成分支。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "preset_voices.json"


class PresetInstruct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene: str = Field(min_length=1)
    template: str = Field(min_length=1)
    emotion_map: dict[str, str] = Field(default_factory=dict)


class PresetVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=32)
    provider_label: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    voice_id: str = Field(min_length=1, max_length=128)
    language: str = Field(min_length=1, max_length=16)
    instruct: PresetInstruct | None = None

    @property
    def cache_key(self) -> str:
        return f"{self.provider}:{self.voice_id}"


LOCAL_PRESET_ID = "local"


class PresetCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_id: str = Field(min_length=1, max_length=64)
    voices: list[PresetVoice] = Field(min_length=1)


@lru_cache
def load_preset_catalog() -> PresetCatalog:
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    catalog = PresetCatalog.model_validate(payload)
    ids = [item.id for item in catalog.voices]
    if len(ids) != len(set(ids)):
        raise ValueError("预设音色 id 重复")
    if catalog.default_id not in ids:
        raise ValueError("默认音色不在目录中")
    return catalog


def default_preset() -> PresetVoice:
    preset = get_preset(load_preset_catalog().default_id)
    if preset is None:
        raise ValueError("默认音色不在目录中")
    return preset


def resolve_stored_preset(stored_id: str | None) -> PresetVoice | None:
    """没有记录、记录已下线，或仍标着已移除的本地合成时，用目录默认音色。"""
    if stored_id == LOCAL_PRESET_ID:
        stored_id = None
    if stored_id:
        found = get_preset(stored_id)
        if found is not None:
            return found
    return default_preset()


def get_preset(preset_id: str) -> PresetVoice | None:
    for item in load_preset_catalog().voices:
        if item.id == preset_id:
            return item
    return None


def render_preset_instruction(preset: PresetVoice, primary_emotion: str, fallback: str) -> str:
    """龙安欢用官方场景句。其余厂商沿用当前回合的表达指令。"""
    instruct = preset.instruct
    if instruct is None:
        return fallback
    api_emotion = instruct.emotion_map.get(primary_emotion, "neutral")
    return instruct.template.format(scene=instruct.scene, api_emotion=api_emotion)


def cache_matches(model_name: str | None, preset_key: str | None) -> bool:
    stored = model_name or ""
    if preset_key:
        return stored.startswith(f"{preset_key}:")
    return not stored.startswith(("fish:", "volcengine:", "dashscope:"))
