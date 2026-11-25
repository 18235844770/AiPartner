"""每个陪伴者只保留一条进行中的会话。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_one_active_conversation"
down_revision: str | None = "0017_companion_voice_preset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY companion_id
                           ORDER BY last_message_at DESC NULLS LAST, created_at DESC
                       ) AS rn
                FROM conversations
                WHERE status = 'active'
            )
            UPDATE conversations AS conversation
            SET status = 'archived',
                archived_at = NOW(),
                updated_at = NOW()
            FROM ranked
            WHERE conversation.id = ranked.id
              AND ranked.rn > 1
            """
        )
    )
    op.create_index(
        "uq_conversations_one_active",
        "conversations",
        ["companion_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_conversations_one_active", table_name="conversations")
