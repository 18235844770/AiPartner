"""补全人格档案，并为开发环境保存可回放的模型调用快照。"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_archive_snapshots"
down_revision: str | None = "0009_local_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARCHIVE_CHECK = """
jsonb_typeof(archive) = 'object'
AND archive ?& ARRAY['identity','background','interests','viewpoints','values','thinking_habits','communication','attention']
AND jsonb_typeof(archive->'identity') = 'string' AND char_length(archive->>'identity') > 0
AND jsonb_typeof(archive->'background') = 'string' AND char_length(archive->>'background') > 0
AND jsonb_typeof(archive->'communication') = 'string' AND char_length(archive->>'communication') > 0
AND jsonb_typeof(archive->'interests') = 'array' AND jsonb_array_length(archive->'interests') >= 1
AND jsonb_typeof(archive->'viewpoints') = 'array' AND jsonb_array_length(archive->'viewpoints') >= 1
AND jsonb_typeof(archive->'values') = 'array' AND jsonb_array_length(archive->'values') >= 1
AND jsonb_typeof(archive->'thinking_habits') = 'array' AND jsonb_array_length(archive->'thinking_habits') >= 1
AND jsonb_typeof(archive->'attention') = 'array' AND jsonb_array_length(archive->'attention') >= 1
"""


def upgrade() -> None:
    op.add_column("persona_versions", sa.Column("archive", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    templates = json.loads(
        (Path(__file__).resolve().parents[2] / "app" / "modules" / "persona" / "data" / "persona_templates.json").read_text(
            encoding="utf-8"
        )
    )
    bind = op.get_bind()
    for item in templates:
        bind.execute(
            sa.text(
                """
                UPDATE persona_versions
                SET archive = CAST(:archive AS jsonb)
                WHERE mbti_type = :mbti AND archive IS NULL
                """
            ),
            {"archive": json.dumps(item["archive"], ensure_ascii=False), "mbti": item["mbti_type"]},
        )
    op.alter_column("persona_versions", "archive", nullable=False)
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK)
    op.add_column("model_call_logs", sa.Column("returned_model_name", sa.String(128), nullable=True))
    op.add_column("model_call_logs", sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("model_call_logs", sa.Column("prompt_snapshot", sa.Text(), nullable=True))
    op.add_column("model_call_logs", sa.Column("messages_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("model_call_logs", sa.Column("response_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("model_call_logs", sa.Column("context_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "model_call_logs",
        sa.Column("detail_retained_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_call_logs", "detail_retained_until")
    op.drop_column("model_call_logs", "context_versions")
    op.drop_column("model_call_logs", "response_snapshot")
    op.drop_column("model_call_logs", "messages_snapshot")
    op.drop_column("model_call_logs", "prompt_snapshot")
    op.drop_column("model_call_logs", "parameters")
    op.drop_column("model_call_logs", "returned_model_name")
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
    op.drop_column("persona_versions", "archive")
