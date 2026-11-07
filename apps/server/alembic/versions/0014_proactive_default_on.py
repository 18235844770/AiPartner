"""将主动交流开关默认打开，并回填已有 companion_states。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_proactive_default_on"
down_revision: str | None = "0013_emotion_v1_levels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 已有陪伴者：把仍为 false / 缺失的 proactive_allowed 打开。
    # quiet_until / mode / 冷却门槛仍会约束实际主动发送。
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET interaction = jsonb_set(interaction, '{proactive_allowed}', 'true'::jsonb, true),
                updated_at = NOW()
            WHERE COALESCE((interaction->>'proactive_allowed')::boolean, false) = false
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE companion_states
            SET interaction = jsonb_set(interaction, '{proactive_allowed}', 'false'::jsonb, true),
                updated_at = NOW()
            WHERE COALESCE((interaction->>'proactive_allowed')::boolean, true) = true
            """
        )
    )
