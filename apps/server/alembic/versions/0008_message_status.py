"""消息状态限定为已记录、生成中、完成、失败和中断。"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_message_status"
down_revision: str | None = "0007_working_and_attention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_messages_status_known",
        "messages",
        "status IN ('recorded', 'generating', 'completed', 'failed', 'interrupted')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_status_known", "messages", type_="check")
