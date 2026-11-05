from enum import StrEnum


class InteractionMode(StrEnum):
    AVAILABLE = "available"
    WAITING = "waiting"
    QUIET = "quiet"
    PAUSED = "paused"


class MotivationKind(StrEnum):
    CONNECT = "connect"
    SHARE = "share"
    LISTEN = "listen"
    COMFORT = "comfort"
    UNDERSTAND = "understand"
    PLAY = "play"
    RESOLVE_CONFLICT = "resolve_conflict"
    REST = "rest"


class StateEventType(StrEnum):
    EMOTION_CHANGED = "emotion_changed"
    RELATIONSHIP_CHANGED = "relationship_changed"
    INTERACTION_CHANGED = "interaction_changed"
    MOTIVATION_CHANGED = "motivation_changed"
    MULTIPLE_CHANGED = "multiple_changed"
    STATE_INITIALIZED = "state_initialized"
    STATE_RECOVERED = "state_recovered"


class StateSourceType(StrEnum):
    USER_MESSAGE = "user_message"
    COMPANION_ACTION = "companion_action"
    DIALOGUE_DECISION = "dialogue_decision"
    BACKGROUND_TASK = "background_task"
    SYSTEM = "system"


_DIMENSION_EVENTS = {
    "emotion": StateEventType.EMOTION_CHANGED,
    "relationship": StateEventType.RELATIONSHIP_CHANGED,
    "interaction": StateEventType.INTERACTION_CHANGED,
    "motivation": StateEventType.MOTIVATION_CHANGED,
}


def event_type_for(dimensions: list[str]) -> StateEventType:
    if len(dimensions) == 1:
        return _DIMENSION_EVENTS[dimensions[0]]
    return StateEventType.MULTIPLE_CHANGED
