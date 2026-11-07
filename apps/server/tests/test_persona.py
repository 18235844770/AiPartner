import random
import uuid

from app.modules.persona.domain.archive import PersonaIdentity
from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates
from app.modules.persona.services.persona_service import PersonaService

_CORE_FIELDS = tuple(PersonaIdentity.model_fields)


def test_templates_cover_the_six_confirmed_types() -> None:
    templates = load_persona_templates()
    assert set(templates) == set(MbtiType)
    assert templates[MbtiType.INFJ].title == "洞察型"
    assert templates[MbtiType.INTP].title == "分析型"


def test_templates_include_v2_core_profile_modules() -> None:
    templates = load_persona_templates()
    for mbti, template in templates.items():
        identity = template.archive.identity
        assert identity.identity_summary
        assert identity.personality_narrative
        for field in _CORE_FIELDS:
            value = getattr(identity, field)
            if isinstance(value, list):
                assert value, f"{mbti.value}.{field} 不能为空"
            else:
                assert str(value).strip(), f"{mbti.value}.{field} 不能为空"
        assert template.archive.interests
        assert template.archive.viewpoints
        assert template.archive.attention
        assert "陪伴者" in template.archive.background
        assert template.archive.self_model.human_identity is False
        assert template.archive.self_model.emotional_capability
        assert template.archive.relationship.attachment_disposition.attachment_tendency
        assert template.archive.relationship.relationship_preferences.emotional_boundaries


def test_initialization_uses_an_explicit_type_instead_of_random() -> None:
    service = PersonaService(rng=random.Random(0))
    profile, version = service._new_profile(
        companion_id=uuid.uuid4(),
        template=service._templates[MbtiType.INTJ],
    )
    assert profile.initial_version_id == version.id
    assert profile.current_version_id == version.id
    assert version.mbti_type == "INTJ"
    assert version.version_number == 1
    assert version.core_traits["title"] == "战略型"
    assert version.core_traits["identity_summary"]
    assert version.core_traits["core_temperament"]
    assert version.behavior_traits["natural_behavior"]
    assert version.behavior_traits["attachment_disposition"]["independence_need"] == "high"
    assert version.communication_preferences["emotional_expression"]
    assert version.communication_preferences["emotional_boundaries"]
    assert version.change_reason == "初始人格"
    identity = version.archive["identity"]
    assert isinstance(identity, dict)
    assert "理性" in str(identity["identity_summary"])
    assert identity["misconceptions"]
    assert version.archive["interests"]
    assert version.archive["self_model"]["human_identity"] is False
    assert version.archive["relationship"]["attachment_disposition"]


def test_random_choice_stays_inside_the_six_types() -> None:
    service = PersonaService(rng=random.Random(7))
    chosen = [service._rng.choice(list(MbtiType)) for _ in range(30)]
    assert set(chosen) <= set(MbtiType)
    assert len(set(chosen)) > 1
