import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.modules.persona.domain.enums import MbtiType

_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "data" / "persona_templates.json"


class PersonaTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mbti_type: MbtiType
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    expression: str = Field(min_length=1)


def load_persona_templates() -> dict[MbtiType, PersonaTemplate]:
    raw = json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("人格模板必须是列表")
    templates = [PersonaTemplate.model_validate(item) for item in raw]
    by_type = {template.mbti_type: template for template in templates}
    expected = set(MbtiType)
    if set(by_type) != expected or len(templates) != len(expected):
        raise ValueError("人格模板必须且只能包含六种已确认的 MBTI 类型")
    return by_type
