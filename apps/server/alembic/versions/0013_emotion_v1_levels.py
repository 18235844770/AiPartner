"""为情绪快照回填十维 levels，并为 interaction 增加 consecutive_quiet_turns。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_emotion_v1_levels"
down_revision: str | None = "0012_attachment_self_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT_LEVELS = (
    '{"joy": 0, "affection": 0, "longing": 0, "comfort": 0, "excitement": 0,'
    ' "sadness": 0, "anxiety": 0, "jealousy": 0, "anger": 0, "hurt": 0}'
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET emotion = jsonb_set(
                emotion,
                '{levels}',
                COALESCE(emotion->'levels', CAST(:levels AS jsonb)),
                true
            )
            WHERE emotion->'levels' IS NULL
               OR jsonb_typeof(emotion->'levels') <> 'object'
            """
        ).bindparams(levels=_DEFAULT_LEVELS)
    )
    # 将遗留 0-1 jealousy 同步进 levels.jealousy（仅在 levels 嫉妒仍为 0 时）。
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET emotion = jsonb_set(
                emotion,
                '{levels,jealousy}',
                to_jsonb(
                    ROUND(
                        COALESCE((emotion->>'jealousy')::numeric, 0) * 100
                    , 2)
                ),
                true
            )
            WHERE COALESCE((emotion->'levels'->>'jealousy')::numeric, 0) = 0
              AND COALESCE((emotion->>'jealousy')::numeric, 0) > 0
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET interaction = jsonb_set(
                interaction,
                '{consecutive_quiet_turns}',
                '0'::jsonb,
                true
            )
            WHERE interaction->'consecutive_quiet_turns' IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET emotion = emotion - 'levels'
            WHERE emotion ? 'levels'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET interaction = interaction - 'consecutive_quiet_turns'
            WHERE interaction ? 'consecutive_quiet_turns'
            """
        )
    )
