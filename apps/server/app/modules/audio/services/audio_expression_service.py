from app.modules.audio.domain.expression import (
    AudioExpression,
    AudioExpressionInput,
    DecisionVoiceCues,
    build_audio_expression,
)
from app.modules.persona.domain.voice_expression import VoiceExpressionProfile


class AudioExpressionService:
    """纯领域换算，不访问数据库、不写 State。"""

    def build(
        self,
        *,
        primary: str,
        secondary: list[str] | None = None,
        levels: dict[str, float] | None = None,
        snapshot_intensity: float = 0.0,
        voice_expression: VoiceExpressionProfile | dict[str, float] | None = None,
        decision: DecisionVoiceCues | None = None,
    ) -> AudioExpression:
        profile = (
            VoiceExpressionProfile.model_validate(voice_expression)
            if isinstance(voice_expression, dict)
            else voice_expression or VoiceExpressionProfile()
        )
        return build_audio_expression(
            AudioExpressionInput(
                primary=primary,
                secondary=secondary or [],
                levels=levels or {},
                snapshot_intensity=snapshot_intensity,
                voice_expression=profile,
                decision=decision,
            )
        )
