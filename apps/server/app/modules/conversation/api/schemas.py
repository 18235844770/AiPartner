import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.conversation.domain.enums import SenderType


class MessageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=128)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    companion_id: uuid.UUID
    title: str | None
    status: str
    next_sequence_number: int
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_type: SenderType
    content: str = Field(min_length=1)
    client_message_id: uuid.UUID | None = None
    metadata: MessageMetadata = Field(default_factory=MessageMetadata)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("消息内容不能为空")
        return stripped


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sequence_number: int
    client_message_id: uuid.UUID | None
    sender_type: str
    content_type: str
    content: str
    status: str
    metadata: dict[str, object]
    created_at: datetime
