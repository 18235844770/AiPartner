"""本地 Embedding：provider 增加 local，记忆向量锁定为 1024 维。"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_local_embedding"
down_revision: str | None = "0008_message_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_model_configs_provider", "model_configs", type_="check")
    op.drop_constraint("ck_model_call_logs_provider", "model_call_logs", type_="check")
    op.execute(
        """
        UPDATE model_configs
        SET provider = 'local'
        WHERE config_key = 'embedding_model' AND provider = 'deepseek'
        """
    )
    op.create_check_constraint(
        "ck_model_configs_provider",
        "model_configs",
        "provider IN ('deepseek', 'local')",
    )
    op.create_check_constraint(
        "ck_model_call_logs_provider",
        "model_call_logs",
        "provider IN ('deepseek', 'local')",
    )
    op.execute(
        """
        DELETE FROM memory_embeddings
        WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 1024
        """
    )
    op.execute(
        """
        ALTER TABLE memory_embeddings
        ALTER COLUMN embedding TYPE vector(1024)
        USING embedding::vector(1024)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE memory_embeddings
        ALTER COLUMN embedding TYPE vector
        USING embedding::vector
        """
    )
    op.execute("DELETE FROM model_call_logs WHERE provider = 'local'")
    op.execute("DELETE FROM model_configs WHERE provider = 'local'")
    op.drop_constraint("ck_model_call_logs_provider", "model_call_logs", type_="check")
    op.drop_constraint("ck_model_configs_provider", "model_configs", type_="check")
    op.create_check_constraint(
        "ck_model_call_logs_provider",
        "model_call_logs",
        "provider IN ('deepseek')",
    )
    op.create_check_constraint(
        "ck_model_configs_provider",
        "model_configs",
        "provider IN ('deepseek')",
    )
