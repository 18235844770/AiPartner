from enum import StrEnum


class TriggerType(StrEnum):
    USER_MESSAGE = "user_message"
    PROACTIVE = "proactive"
    SYSTEM_EVENT = "system_event"
    BACKGROUND = "background"


class DialogueAction(StrEnum):
    """产品方案第四节的基础行为。数据库稿里的 comfort、analyze 等未纳入该集合。"""

    RESPOND = "respond"
    SHARE = "share"
    ASK = "ask"
    REACT = "react"
    CONTINUE = "continue"
    CLOSE = "close"
    QUIET = "quiet"


class TopicTransition(StrEnum):
    CONTINUE = "continue"
    NEW_TOPIC = "new_topic"
    CLOSE = "close"
    NONE = "none"


class DecisionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
