"""每个陪伴者保存一个可切换的云端音色。空记录表示继续用本地音色。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_companion_voice_preset"
down_revision: str | None = "0016_audio_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companion_voice_presets",
        sa.Column("companion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preset_id", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_companion_voice_presets_companion_id_companions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("companion_id", name="pk_companion_voice_presets"),
        sa.CheckConstraint("char_length(preset_id) > 0", name="ck_companion_voice_presets_preset_id_nonempty"),
    )


def downgrade() -> None:
    op.drop_table("companion_voice_presets")
