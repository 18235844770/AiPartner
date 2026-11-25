"""Audio Expression：把 State / Persona 转为 TTS 内部契约。不写 Emotion State。

没有厂商专用指令时，风格提示保持短英文。
中文决策摘要、情绪说明不得写入指令，避免被朗读进语音。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.persona.domain.voice_expression import VoiceExpressionProfile
from app.modules.state.domain.emotion import EMOTION_KEYS, EMOTION_LABELS
from app.shared.speech_marks import strip_non_speech_marks

# 变更 instruct 契约时递增，用于使旧 TTS 缓存失效。
# v5：合成对齐 A_raw（官方 text_frontend + 正确限幅），旧缓存不可复用。
TTS_CONTRACT_VERSION = 5

_LABEL_TO_KEY = {label: key for key, label in EMOTION_LABELS.items() if key in EMOTION_KEYS}
_LABEL_TO_KEY["平静"] = "calm"

# 自由指令：仅英文，避免被念出
_EN_DIRECTION: dict[str, str] = {
    "joy": "cheerful and light",
    "affection": "warm and gentle",
    "longing": "soft and slightly longing",
    "comfort": "calm and soothing",
    "excitement": "lively and energetic",
    "sadness": "slow and subdued",
    "anxiety": "hesitant and uneasy",
    "jealousy": "slightly sour and dissatisfied",
    "anger": "firm and assertive",
    "hurt": "hurt but restrained",
    "calm": "natural and steady",
}

_SPEED: dict[str, float] = {
    "joy": 1.05,
    "affection": 0.98,
    "longing": 0.95,
    "comfort": 0.98,
    "excitement": 1.12,
    "sadness": 0.9,
    "anxiety": 0.95,
    "jealousy": 1.0,
    "anger": 1.08,
    "hurt": 0.92,
    "calm": 1.0,
}

__all__ = [
    "AudioExpression",
    "AudioExpressionInput",
    "DecisionVoiceCues",
    "TTS_CONTRACT_VERSION",
    "VoiceExpressionProfile",
    "build_audio_expression",
    "normalize_emotion_key",
    "prepare_speak_text",
]


class DecisionVoiceCues(BaseModel):
    """已校验决策中可用于表达的线索。仅影响风格强度，不得进入可朗读文本。"""

    model_config = ConfigDict(extra="forbid")

    primary_action: str = Field(min_length=1, max_length=32)
    emotional_summary: str | None = Field(default=None, max_length=200)
    motivation_summary: str | None = Field(default=None, max_length=200)


class AudioExpressionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=32)
    secondary: list[str] = Field(default_factory=list)
    levels: dict[str, float] = Field(default_factory=dict)
    snapshot_intensity: float = Field(default=0.0, ge=0, le=1)
    voice_expression: VoiceExpressionProfile = Field(default_factory=VoiceExpressionProfile)
    decision: DecisionVoiceCues | None = None

    @field_validator("secondary")
    @classmethod
    def clean_secondary(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned


class AudioExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_emotion: str
    secondary_emotions: list[str] = Field(default_factory=list)
    intensity: float = Field(ge=0, le=1)
    intensity_source_level: float = Field(ge=0, le=100)
    expression_style: str
    speed: float = Field(gt=0.5, le=2.0)
    volume: float = Field(gt=0.1, le=2.0)
    pause_style: str
    tts_instruction: str = Field(min_length=1, max_length=500)
    contract_version: int = TTS_CONTRACT_VERSION


def prepare_speak_text(content: str) -> str:
    """仅保留应对用户朗读的回复正文，去掉不应开口的元信息。"""
    import re

    text = (content or "").strip()
    if not text:
        return ""
    # 防御：若正文误夹带 JSON / 决策字段，截到第一段自然语言
    if text.startswith("{") and '"primary_action"' in text:
        return ""
    # 去掉明显的决策标注行
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        lower = stripped.lower()
        if lower.startswith(("primary_action", "motivation", "emotional_summary", "decision:")):
            continue
        if stripped.startswith(("决策：", "意图：", "动机：", "【决策", "[decision")):
            continue
        lines.append(line)
    text = strip_non_speech_marks("\n".join(lines).strip())
    # 换行在 TTS 里常变成突兀气口；按句读收口，减轻顿挫
    parts = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    if not parts:
        return ""
    merged = parts[0]
    for part in parts[1:]:
        if merged[-1] in "。！？；，、!?":
            merged = f"{merged}{part}"
        else:
            merged = f"{merged}，{part}"
    return merged.strip()


def build_audio_expression(data: AudioExpressionInput) -> AudioExpression:
    primary_key = normalize_emotion_key(data.primary)
    secondary_keys = [normalize_emotion_key(item) for item in data.secondary]
    secondary_keys = [key for key in secondary_keys if key != primary_key and key != "calm"]
    level = _level_for(primary_key, data.levels, data.snapshot_intensity)
    intensity = round(level / 100.0, 3)
    band = _band(level)
    persona = data.voice_expression
    base_speed = _SPEED.get(primary_key, 1.0)
    speed = round(base_speed * persona.speaking_pace, 3)
    speed = min(1.5, max(0.75, speed))
    if band == "none":
        intensity = 0.0
    effective = round(intensity * persona.emotional_expressiveness, 3)
    style = _style(primary_key, secondary_keys, band, persona)
    instruction = _instruction(primary_key, secondary_keys, band, effective, persona)
    pause = "short" if persona.pause_preference < 0.35 else "long" if persona.pause_preference > 0.65 else "natural"
    # 合成默认偏小；过高增益再硬裁切会碎音。1.25 足够听清且少失真。
    volume = 1.25
    return AudioExpression(
        primary_emotion=primary_key,
        secondary_emotions=secondary_keys[:3],
        intensity=effective,
        intensity_source_level=level,
        expression_style=style,
        speed=speed,
        volume=volume,
        pause_style=pause,
        tts_instruction=instruction,
        contract_version=TTS_CONTRACT_VERSION,
    )


def normalize_emotion_key(label: str) -> str:
    text = label.strip()
    if not text:
        return "calm"
    lower = text.lower()
    if lower in EMOTION_KEYS or lower == "calm":
        return lower
    if text in _LABEL_TO_KEY:
        return _LABEL_TO_KEY[text]
    return "calm"


def _level_for(key: str, levels: dict[str, float], snapshot_intensity: float) -> float:
    if key == "calm":
        return 0.0
    raw = levels.get(key)
    if raw is None:
        return round(max(0.0, min(100.0, snapshot_intensity * 100.0)), 2)
    return round(max(0.0, min(100.0, float(raw))), 2)


def _band(level: float) -> str:
    if level < 20:
        return "none"
    if level < 40:
        return "light"
    if level < 60:
        return "medium"
    if level < 80:
        return "strong"
    return "intense"


def _style(primary: str, secondary: list[str], band: str, persona: VoiceExpressionProfile) -> str:
    if band == "none":
        return "neutral"
    parts = [primary]
    parts.extend(secondary[:2])
    tone = "expressive" if persona.expressiveness >= 0.7 else "restrained"
    return f"{'_'.join(parts)}_{band}_{tone}"


def _instruction(
    primary: str,
    secondary: list[str],
    band: str,
    intensity: float,
    persona: VoiceExpressionProfile,
) -> str:
    """生成短英文风格提示，供云端音色使用。禁止中文、禁止决策摘要。"""
    if band == "none" or intensity <= 0:
        return "Speak naturally and calmly."
    tone = _EN_DIRECTION.get(primary, "natural")
    bits = [f"Speak in a {tone} voice"]
    if secondary:
        extra = ", ".join(_EN_DIRECTION.get(item, item) for item in secondary[:2])
        bits.append(f"with a hint of {extra}")
    if persona.directness >= 0.7:
        bits.append("be direct")
    elif persona.directness <= 0.3:
        bits.append("stay restrained")
    if band in {"strong", "intense"}:
        bits.append("emotion may be clear but never shout")
    else:
        bits.append("keep emotion moderate")
    # 注意：故意不读取 DecisionVoiceCues —— 决策内容不得进入语音
    return ". ".join(bits) + "."
