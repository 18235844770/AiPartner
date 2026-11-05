from enum import StrEnum

# 设计文档要求 messages.status，但没有枚举取值。
# recorded 只表示原始消息已经落库，不代表后续投递状态机。
MESSAGE_STATUS_RECORDED = "recorded"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SenderType(StrEnum):
    USER = "user"
    COMPANION = "companion"
    SYSTEM = "system"


class ContentType(StrEnum):
    TEXT = "text"
