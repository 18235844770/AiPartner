"""把最近一段对话收成工作记忆摘要。不新增正式记忆，也不改当前话题。"""

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.memory.domain.enums import OpenThreadStatus
from app.modules.model_adapter.domain.messages import ChatMessage


class SummaryThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    status: OpenThreadStatus

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("不能为空")
        return stripped


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    open_threads: list[SummaryThread] = Field(default_factory=list, max_length=8)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("摘要不能为空")
        return stripped


_SYSTEM = (
    "你只输出一个 JSON 对象，包含 summary 和 open_threads。"
    "summary 用一两句话概括这段对话里还没结束的上下文。"
    "不要把它写成可以长期保存的用户事实，也不要把推断说成用户明确说过的话。"
    "open_threads 只列出仍未完成或这一轮刚刚结束的事项。"
    "title 是事项名称，status 只能是 open 或 closed。"
    "current_topic 只是给你参考，不要输出它，调用方不会用你的结果改话题。"
    "不要评价关系远近。没有把握时，summary 只复述已经出现的内容，open_threads 可以为空。"
)


def summary_messages(context: dict[str, object]) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=_SYSTEM),
        ChatMessage(role="user", content=json.dumps(context, ensure_ascii=False)),
    ]
