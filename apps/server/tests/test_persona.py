import random
import uuid

from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates
from app.modules.persona.services.persona_service import PersonaService


def test_templates_cover_the_six_confirmed_types() -> None:
    templates = load_persona_templates()
    assert set(templates) == set(MbtiType)
    assert templates[MbtiType.INFJ].title == "洞察型"
    assert templates[MbtiType.INTP].title == "分析型"


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
    assert version.change_reason == "初始人格"


def test_random_choice_stays_inside_the_six_types() -> None:
    service = PersonaService(rng=random.Random(7))
    chosen = [service._rng.choice(list(MbtiType)) for _ in range(30)]
    assert set(chosen) <= set(MbtiType)
    assert len(set(chosen)) > 1
