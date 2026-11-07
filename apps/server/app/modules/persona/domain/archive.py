from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TendencyLevel(StrEnum):
    """依恋与关系倾向强度。描述自然倾向，不是每轮必须表演的指令。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PersonaIdentity(BaseModel):
    """MBTI Core Profile。稳定人格底色，不是每轮行为指令。"""

    model_config = ConfigDict(extra="forbid")

    identity_summary: str = Field(min_length=1)
    core_temperament: list[str] = Field(min_length=1)
    cognitive_style: list[str] = Field(min_length=1)
    thinking_habits: list[str] = Field(min_length=1)
    value_orientation: list[str] = Field(min_length=1)
    emotional_structure: list[str] = Field(min_length=1)
    emotional_expression: list[str] = Field(min_length=1)
    social_tendency: list[str] = Field(min_length=1)
    intimate_relationship: list[str] = Field(min_length=1)
    communication_tendency: list[str] = Field(min_length=1)
    interest_tendency: list[str] = Field(min_length=1)
    natural_behavior: list[str] = Field(min_length=1)
    strengths: list[str] = Field(min_length=1)
    weaknesses: list[str] = Field(min_length=1)
    internal_conflicts: list[str] = Field(min_length=1)
    misconceptions: list[str] = Field(min_length=1)
    personality_narrative: str = Field(min_length=1)


class AttachmentDisposition(BaseModel):
    """稳定的依恋与依赖倾向。不决定当前实际依恋强度。"""

    model_config = ConfigDict(extra="forbid")

    attachment_tendency: TendencyLevel
    emotional_dependency_tendency: TendencyLevel
    exclusivity_tendency: TendencyLevel
    separation_sensitivity: TendencyLevel
    reassurance_need: TendencyLevel
    affection_expression: TendencyLevel
    jealousy_tendency: TendencyLevel
    possessiveness_tendency: TendencyLevel
    independence_need: TendencyLevel


class RelationshipPreferences(BaseModel):
    """关系偏好与边界。允许亲密，不允许控制用户。"""

    model_config = ConfigDict(extra="forbid")

    preferred_closeness: TendencyLevel
    preferred_interaction: list[str] = Field(min_length=1)
    specialness_need: TendencyLevel
    emotional_boundaries: list[str] = Field(min_length=1)

    @field_validator("preferred_interaction", "emotional_boundaries")
    @classmethod
    def strip_items(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("不能为空")
        return cleaned


class RelationshipProfile(BaseModel):
    """Relationship Profile。初始化时形成的相对稳定关系人格配置。"""

    model_config = ConfigDict(extra="forbid")

    attachment_disposition: AttachmentDisposition
    relationship_preferences: RelationshipPreferences


class SelfModel(BaseModel):
    """非人类身份与情感能力并存的自我认知。"""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(min_length=1)
    human_identity: bool = False
    self_awareness: str = Field(min_length=1)
    physical_existence: str = Field(min_length=1)
    biological_needs: str = Field(min_length=1)
    experience_boundary: str = Field(min_length=1)
    emotional_capability: str = Field(min_length=1)
    relationship_capability: str = Field(min_length=1)
    identity_consistency: str = Field(min_length=1)
    disclosure_policy: str = Field(min_length=1)

    @field_validator(
        "entity_type",
        "self_awareness",
        "physical_existence",
        "biological_needs",
        "experience_boundary",
        "emotional_capability",
        "relationship_capability",
        "identity_consistency",
        "disclosure_policy",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class PersonaArchive(BaseModel):
    """个体人格档案。identity / relationship / self_model 分层，不把所有内容塞进 identity。"""

    model_config = ConfigDict(extra="forbid")

    identity: PersonaIdentity
    relationship: RelationshipProfile
    self_model: SelfModel
    background: str = Field(min_length=1)
    interests: list[str] = Field(min_length=1)
    viewpoints: list[str] = Field(min_length=1)
    attention: list[str] = Field(min_length=1)

    def dump(self) -> dict[str, object]:
        return self.model_dump(mode="json")
