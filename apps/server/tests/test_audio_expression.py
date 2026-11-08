from app.modules.audio.domain.expression import (
    AudioExpressionInput,
    DecisionVoiceCues,
    TTS_CONTRACT_VERSION,
    VoiceExpressionProfile,
    build_audio_expression,
    normalize_emotion_key,
    prepare_speak_text,
)


def test_normalize_emotion_accepts_chinese_and_english() -> None:
    assert normalize_emotion_key("开心") == "joy"
    assert normalize_emotion_key("joy") == "joy"
    assert normalize_emotion_key("平静") == "calm"


def test_expression_uses_levels_not_snapshot_when_present() -> None:
    result = build_audio_expression(
        AudioExpressionInput(
            primary="开心",
            secondary=["亲密"],
            levels={"joy": 65, "affection": 40},
            snapshot_intensity=0.2,
            voice_expression=VoiceExpressionProfile(emotional_expressiveness=1.0, speaking_pace=1.0),
        )
    )
    assert result.primary_emotion == "joy"
    assert result.secondary_emotions == ["affection"]
    assert result.intensity_source_level == 65
    assert result.intensity == 0.65
    assert "cheerful" in result.tts_instruction.lower() or "light" in result.tts_instruction.lower()
    assert result.contract_version == TTS_CONTRACT_VERSION
    assert result.volume >= 1.5


def test_low_level_skips_noticeable_emotion() -> None:
    result = build_audio_expression(
        AudioExpressionInput(
            primary="anger",
            levels={"anger": 10},
            snapshot_intensity=1.0,
        )
    )
    assert result.intensity == 0.0
    assert result.expression_style == "neutral"
    assert "calm" in result.tts_instruction.lower() or "naturally" in result.tts_instruction.lower()


def test_persona_speaking_pace_affects_speed() -> None:
    calm = build_audio_expression(
        AudioExpressionInput(
            primary="excitement",
            levels={"excitement": 70},
            voice_expression=VoiceExpressionProfile(speaking_pace=0.8, emotional_expressiveness=1.0),
        )
    )
    lively = build_audio_expression(
        AudioExpressionInput(
            primary="excitement",
            levels={"excitement": 70},
            voice_expression=VoiceExpressionProfile(speaking_pace=1.2, emotional_expressiveness=1.0),
        )
    )
    assert lively.speed > calm.speed


def test_decision_cue_never_enters_tts_instruction() -> None:
    result = build_audio_expression(
        AudioExpressionInput(
            primary="affection",
            levels={"affection": 55},
            voice_expression=VoiceExpressionProfile(emotional_expressiveness=1.0),
            decision=DecisionVoiceCues(
                primary_action="respond",
                emotional_summary="想安慰对方并分享自己的紧张",
                motivation_summary="维持亲密并确认语音效果",
            ),
        )
    )
    assert "想安慰对方" not in result.tts_instruction
    assert "分享" not in result.tts_instruction
    assert "动机" not in result.tts_instruction
    assert "意图" not in result.tts_instruction
    # instruct 必须是英文，避免 CosyVoice 朗读
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in result.tts_instruction)


def test_prepare_speak_text_strips_decision_lines() -> None:
    raw = "你好。\n意图：想安慰用户\n决策：respond\n我在这儿。"
    cleaned = prepare_speak_text(raw)
    assert "意图" not in cleaned
    assert "决策" not in cleaned
    assert "你好" in cleaned
    assert "我在这儿" in cleaned
