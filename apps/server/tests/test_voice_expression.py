from app.modules.audio.domain.expression import AudioExpressionInput, build_audio_expression
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.voice_expression import (
    default_voice_expression,
    load_voice_expression_profiles,
    resolve_voice_expression,
)


def test_voice_profiles_cover_six_mbti() -> None:
    profiles = load_voice_expression_profiles()
    assert set(profiles) == {item.value for item in MbtiType}
    assert profiles["ENFP"].emotional_expressiveness > profiles["INTJ"].emotional_expressiveness
    assert profiles["ENFP"].speaking_pace > profiles["INFP"].speaking_pace


def test_resolve_falls_back_to_mbti_defaults() -> None:
    resolved = resolve_voice_expression({}, mbti_type="ENFP")
    assert resolved.expressiveness == default_voice_expression("ENFP").expressiveness


def test_resolve_reads_behavior_traits() -> None:
    resolved = resolve_voice_expression(
        {
            "voice_expression": {
                "expressiveness": 0.2,
                "speaking_pace": 0.8,
                "intonation_variation": 0.3,
                "emotional_expressiveness": 0.2,
                "pause_preference": 0.9,
                "directness": 0.1,
            }
        },
        mbti_type="ENFP",
    )
    assert resolved.expressiveness == 0.2
    assert resolved.directness == 0.1


def test_same_emotion_differs_by_persona() -> None:
    enfp = build_audio_expression(
        AudioExpressionInput(
            primary="joy",
            levels={"joy": 70},
            voice_expression=default_voice_expression("ENFP"),
        )
    )
    intj = build_audio_expression(
        AudioExpressionInput(
            primary="joy",
            levels={"joy": 70},
            voice_expression=default_voice_expression("INTJ"),
        )
    )
    assert enfp.speed > intj.speed
    assert enfp.intensity >= intj.intensity
    assert "Speak" in enfp.tts_instruction
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in enfp.tts_instruction)
