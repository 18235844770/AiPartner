from pydantic import BaseModel, ConfigDict, Field


class PersonaArchive(BaseModel):
    """完整初始人格档案。核心类型仍由 mbti_type 单独保存。"""

    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=1)
    background: str = Field(min_length=1)
    interests: list[str] = Field(min_length=1)
    viewpoints: list[str] = Field(min_length=1)
    values: list[str] = Field(min_length=1)
    thinking_habits: list[str] = Field(min_length=1)
    communication: str = Field(min_length=1)
    attention: list[str] = Field(min_length=1)

    def dump(self) -> dict[str, object]:
        return self.model_dump(mode="json")
