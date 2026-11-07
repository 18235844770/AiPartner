"""为 Relationship Profile 回填 self_assertion，并收紧档案校验。"""

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0015_rel_self_assertion"
down_revision: str | None = "0014_proactive_default_on"
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
_ARCHIVE_CHECK_V22 = (
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
    " AND archive->'relationship' ?& ARRAY['attachment_disposition','relationship_preferences','self_assertion']"
    " AND jsonb_typeof(archive->'relationship'->'attachment_disposition') = 'object'"
    " AND jsonb_typeof(archive->'relationship'->'relationship_preferences') = 'object'"
    " AND jsonb_typeof(archive->'relationship'->'self_assertion') = 'object'"
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

_DEFAULT_ASSERTION = {
    "assertiveness": "medium",
    "resentment_tendency": "medium",
    "confrontation_tendency": "medium",
    "forgiveness_tendency": "medium",
}


def upgrade() -> None:
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
    relationships = json.loads((_DATA / "relationship_profiles.json").read_text(encoding="utf-8"))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, mbti_type, archive FROM persona_versions")).mappings().all()
    for row in rows:
        archive = row["archive"]
        if not isinstance(archive, dict):
            continue
        relationship = archive.get("relationship")
        if not isinstance(relationship, dict):
            continue
        existing = relationship.get("self_assertion")
        template = relationships.get(row["mbti_type"], {}).get("self_assertion", _DEFAULT_ASSERTION)
        if isinstance(existing, dict):
            merged = {**template, **{key: value for key, value in existing.items() if value is not None}}
        else:
            merged = dict(template)
        for key, value in _DEFAULT_ASSERTION.items():
            merged.setdefault(key, value)
        relationship = {**relationship, "self_assertion": merged}
        archive = {**archive, "relationship": relationship}
        bind.execute(
            sa.text("UPDATE persona_versions SET archive = CAST(:archive AS jsonb) WHERE id = :id"),
            {"archive": json.dumps(archive, ensure_ascii=False), "id": row["id"]},
        )
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK_V22)


def downgrade() -> None:
    op.drop_constraint("ck_persona_versions_archive_sections", "persona_versions", type_="check")
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, archive FROM persona_versions")).mappings().all()
    for row in rows:
        archive = row["archive"]
        if not isinstance(archive, dict):
            continue
        relationship = archive.get("relationship")
        if not isinstance(relationship, dict) or "self_assertion" not in relationship:
            continue
        relationship = {key: value for key, value in relationship.items() if key != "self_assertion"}
        archive = {**archive, "relationship": relationship}
        bind.execute(
            sa.text("UPDATE persona_versions SET archive = CAST(:archive AS jsonb) WHERE id = :id"),
            {"archive": json.dumps(archive, ensure_ascii=False), "id": row["id"]},
        )
    op.create_check_constraint("ck_persona_versions_archive_sections", "persona_versions", _ARCHIVE_CHECK_V21)
