import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.modules.persona.domain.archive import PersonaArchive
from app.modules.persona.domain.enums import MbtiType

_DATA = Path(__file__).resolve().parents[1] / "data"
_TEMPLATE_PATH = _DATA / "persona_templates.json"
_RELATIONSHIP_PATH = _DATA / "relationship_profiles.json"
_SELF_MODEL_PATH = _DATA / "self_model.json"


class PersonaTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mbti_type: MbtiType
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    archive: PersonaArchive


def load_persona_templates() -> dict[MbtiType, PersonaTemplate]:
    raw = json.loads(_TEMPLATE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("人格模板必须是列表")
    relationships = json.loads(_RELATIONSHIP_PATH.read_text(encoding="utf-8"))
    self_model = json.loads(_SELF_MODEL_PATH.read_text(encoding="utf-8"))
    if not isinstance(relationships, dict) or not isinstance(self_model, dict):
        raise ValueError("关系倾向与自我认知配置必须是对象")
    templates: list[PersonaTemplate] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("人格模板项必须是对象")
        archive = item.get("archive")
        if not isinstance(archive, dict):
            raise ValueError("人格档案必须是对象")
        mbti = item.get("mbti_type")
        if mbti not in relationships:
            raise ValueError(f"缺少 {mbti} 的关系倾向配置")
        enriched = {
            **item,
            "archive": {
                **archive,
                "relationship": archive.get("relationship") or relationships[mbti],
                "self_model": archive.get("self_model") or self_model,
            },
        }
        templates.append(PersonaTemplate.model_validate(enriched))
    by_type = {template.mbti_type: template for template in templates}
    expected = set(MbtiType)
    if set(by_type) != expected or len(templates) != len(expected):
        raise ValueError("人格模板必须且只能包含六种已确认的 MBTI 类型")
    if set(relationships) != {item.value for item in MbtiType}:
        raise ValueError("关系倾向配置必须且只能包含六种已确认的 MBTI 类型")
    return by_type
