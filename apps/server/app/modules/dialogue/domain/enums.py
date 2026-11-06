from enum import StrEnum


class TriggerType(StrEnum):
    USER_MESSAGE = "user_message"
    PROACTIVE = "proactive"
    SYSTEM_EVENT = "system_event"
    BACKGROUND = "background"


class DialogueAction(StrEnum):
    """交流主行为与辅助行为：respond、share、ask、react、continue、close、quiet。"""

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
