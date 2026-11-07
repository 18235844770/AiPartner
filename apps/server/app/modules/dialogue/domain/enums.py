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


class SelfMotivationKind(StrEnum):
    """交流动机类型，不是主行为。可以为 none，不要求每轮强行产生。"""

    SHARE_INTEREST = "share_interest"
    SHARE_THOUGHT = "share_thought"
    SHARE_EXPERIENCE = "share_experience"
    EXPRESS_EMOTION = "express_emotion"
    SHOW_CARE = "show_care"
    SEEK_CONNECTION = "seek_connection"
    CONTINUE_TOPIC = "continue_topic"
    RECALL_MEMORY = "recall_memory"
    SEEK_ATTENTION = "seek_attention"
    PLAYFUL_INTERACTION = "playful_interaction"
    EXPRESS_OPINION = "express_opinion"
    NONE = "none"


class DecisionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
