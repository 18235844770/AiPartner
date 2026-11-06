from enum import StrEnum


class MessageStatus(StrEnum):
    RECORDED = "recorded"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


MESSAGE_STATUS_RECORDED = MessageStatus.RECORDED.value


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SenderType(StrEnum):
    USER = "user"
    COMPANION = "companion"
    SYSTEM = "system"


class ContentType(StrEnum):
    TEXT = "text"
