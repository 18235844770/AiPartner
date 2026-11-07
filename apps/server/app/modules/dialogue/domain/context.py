from app.modules.dialogue.domain.context_builder import decision_messages, realization_messages
from app.modules.dialogue.domain.enums import DialogueAction
from app.modules.dialogue.domain.suggestion import ModelDecisionSuggestion

__all__ = ["decision_messages", "final_send", "realization_messages"]


def final_send(suggestion: ModelDecisionSuggestion) -> tuple[DialogueAction, bool]:
    """Quiet 或不发送时，最终行为是 Quiet，并且不生成消息。"""
    if suggestion.primary_action == DialogueAction.QUIET or not suggestion.should_send:
        return DialogueAction.QUIET, False
    return suggestion.primary_action, True
