"""将人格档案升级为 V2.0 Core Profile 结构。"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0011_persona_archive_v2"
down_revision: str | None = "0010_archive_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITY_LIST_KEYS = (
    "core_temperament",
    "cognitive_style",
    "thinking_habits",
    "value_orientation",
    "emotional_structure",
    "emotional_expression",
    "social_tendency",
    "intimate_relationship",
    "communication_tendency",
    "interest_tendency",
    "natural_behavior",
    "strengths",
    "weaknesses",
    "internal_conflicts",
    "misconceptions",
)
_ARCHIVE_IDENTITY_LIST_CHECKS = " AND ".join(
    f"jsonb_typeof(archive->'identity'->'{key}') = 'array'"
    f" AND jsonb_array_length(archive->'identity'->'{key}') >= 1"
    for key in _IDENTITY_LIST_KEYS
)
_ARCHIVE_CHECK_V2 = (
    "jsonb_typeof(archive) = 'object'"
    " AND archive ?& ARRAY['identity','background','interests','viewpoints','attention']"
    " AND jsonb_typeof(archive->'identity') = 'object'"
    " AND archive->'identity' ?& ARRAY["
    "'identity_summary','core_temperament','cognitive_style','thinking_habits',"
    "'value_orientation','emotional_structure','emotional_expression','social_tendency',"
    "'intimate_relationship','communication_tendency','interest_tendency','natural_behavior',"
    "'strengths','weaknesses','internal_conflicts','misconceptions','personality_narrative']"
    " AND jsonb_typeof(archive->'identity'->'identity_summary') = 'string'"
    " AND char_length(archive->'identity'->>'identity_summary') > 0"
    " AND jsonb_typeof(archive->'identity'->'personality_narrative') = 'string'"
    " AND char_length(archive->'identity'->>'personality_narrative') > 0"
    f" AND {_ARCHIVE_IDENTITY_LIST_CHECKS}"
    " AND jsonb_typeof(archive->'background') = 'string' AND char_length(archive->>'background') > 0"
    " AND jsonb_typeof(archive->'interests') = 'array' AND jsonb_array_length(archive->'interests') >= 1"
    " AND jsonb_typeof(archive->'viewpoints') = 'array' AND jsonb_array_length(archive->'viewpoints') >= 1"
    " AND jsonb_typeof(archive->'attention') = 'array' AND jsonb_array_length(archive->'attention') >= 1"
)
_ARCHIVE_CHECK_V1 = """
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
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
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
                WHERE mbti_type = :mbti
                  AND jsonb_typeof(archive->'identity') <> 'object'
                """
            ),
            {"archive": json.dumps(item["archive"], ensure_ascii=False), "mbti": item["mbti_type"]},
        )
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK_V2)


def downgrade() -> None:
    # 降级只恢复约束形状；已写入的 V2 档案无法无损还原为 V1 字符串 identity。
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK_V1)
