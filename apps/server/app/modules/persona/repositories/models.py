import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.persona.domain.enums import MbtiType
from app.shared.database.base import Base
from app.shared.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.shared.database.types import JSONB, UUID

_MBTI_CHECK = "mbti_type IN (" + ", ".join(f"'{item.value}'" for item in MbtiType) + ")"
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
_ARCHIVE_CHECK = (
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


class PersonaProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "persona_profiles"
    __table_args__ = (
        UniqueConstraint("companion_id", name="uq_persona_profiles_companion_id"),
        ForeignKeyConstraint(
            ["companion_id"],
            ["companions.id"],
            name="fk_persona_profiles_companion_id_companions",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "initial_version_id"],
            ["persona_versions.persona_profile_id", "persona_versions.id"],
            name="fk_persona_profiles_initial_version",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["persona_versions.persona_profile_id", "persona_versions.id"],
            name="fk_persona_profiles_current_version",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    companion_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    initial_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class PersonaVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "persona_versions"
    __table_args__ = (
        UniqueConstraint("persona_profile_id", "id", name="uq_persona_versions_profile_id"),
        UniqueConstraint("persona_profile_id", "version_number", name="uq_persona_versions_profile_version"),
        ForeignKeyConstraint(
            ["persona_profile_id"],
            ["persona_profiles.id"],
            name="fk_persona_versions_persona_profile_id_persona_profiles",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_MBTI_CHECK, name="mbti_type"),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("char_length(change_reason) > 0", name="change_reason_nonempty"),
        CheckConstraint(_ARCHIVE_CHECK, name="ck_persona_versions_archive_sections"),
    )

    persona_profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mbti_type: Mapped[str] = mapped_column(String(4), nullable=False)
    core_traits: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    behavior_traits: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    communication_preferences: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    archive: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
