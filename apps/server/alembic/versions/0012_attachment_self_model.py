"""为人格档案补充依恋倾向与 Self Model，并回填现有档案。"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0012_attachment_self_model"
down_revision: str | None = "0011_persona_archive_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA = Path(__file__).resolve().parents[2] / "app" / "modules" / "persona" / "data"
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
_ARCHIVE_CHECK_V21 = (
    "jsonb_typeof(archive) = 'object'"
    " AND archive ?& ARRAY['identity','relationship','self_model','background','interests','viewpoints','attention']"
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
    " AND jsonb_typeof(archive->'relationship') = 'object'"
    " AND archive->'relationship' ?& ARRAY['attachment_disposition','relationship_preferences']"
    " AND jsonb_typeof(archive->'relationship'->'attachment_disposition') = 'object'"
    " AND jsonb_typeof(archive->'relationship'->'relationship_preferences') = 'object'"
    " AND jsonb_typeof(archive->'self_model') = 'object'"
    " AND archive->'self_model' ?& ARRAY["
    "'entity_type','human_identity','self_awareness','physical_existence','biological_needs',"
    "'experience_boundary','emotional_capability','relationship_capability',"
    "'identity_consistency','disclosure_policy']"
    " AND (archive->'self_model'->>'human_identity') = 'false'"
    " AND jsonb_typeof(archive->'background') = 'string' AND char_length(archive->>'background') > 0"
    " AND jsonb_typeof(archive->'interests') = 'array' AND jsonb_array_length(archive->'interests') >= 1"
    " AND jsonb_typeof(archive->'viewpoints') = 'array' AND jsonb_array_length(archive->'viewpoints') >= 1"
    " AND jsonb_typeof(archive->'attention') = 'array' AND jsonb_array_length(archive->'attention') >= 1"
)
_ARCHIVE_CHECK_V2 = (
    "jsonb_typeof(archive) = 'object'"
    " AND archive ?& ARRAY['identity','background','interests','viewpoints','attention']"
    " AND jsonb_typeof(archive->'identity') = 'object'"
)


def upgrade() -> None:
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
    templates = json.loads((_DATA / "persona_templates.json").read_text(encoding="utf-8"))
    relationships = json.loads((_DATA / "relationship_profiles.json").read_text(encoding="utf-8"))
    self_model = json.loads((_DATA / "self_model.json").read_text(encoding="utf-8"))
    bind = op.get_bind()
    for item in templates:
        archive = {
            **item["archive"],
            "relationship": item["archive"].get("relationship") or relationships[item["mbti_type"]],
            "self_model": item["archive"].get("self_model") or self_model,
        }
        bind.execute(
            sa.text(
                """
                UPDATE persona_versions
                SET archive = CAST(:archive AS jsonb)
                WHERE mbti_type = :mbti
                  AND (
                    archive->'relationship' IS NULL
                    OR archive->'self_model' IS NULL
                    OR jsonb_typeof(archive->'relationship') <> 'object'
                    OR jsonb_typeof(archive->'self_model') <> 'object'
                  )
                """
            ),
            {"archive": json.dumps(archive, ensure_ascii=False), "mbti": item["mbti_type"]},
        )
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK_V21)


def downgrade() -> None:
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK_V2)
