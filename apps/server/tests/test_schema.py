import re
from pathlib import Path

from sqlalchemy import CheckConstraint

from app.modules.conversation.repositories.models import Conversation, Message
from app.modules.dialogue.repositories.models import DialogueDecision
from app.modules.identity.repositories.models import Companion, User
from app.modules.infrastructure.repositories.models import BackgroundTask, ModelCallLog, ModelConfig
from app.modules.memory.repositories.models import Memory, MemoryEmbedding
from app.modules.persona.repositories.models import PersonaProfile, PersonaVersion
from app.modules.state.repositories.models import CompanionState, StateEvent
from app.shared.database.base import Base


def test_core_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "companions",
        "conversations",
        "messages",
        "persona_profiles",
        "persona_versions",
        "memories",
        "memory_versions",
        "memory_sources",
        "memory_relations",
        "memory_embeddings",
        "companion_states",
        "state_events",
        "dialogue_decisions",
        "model_configs",
        "model_call_logs",
        "background_tasks",
    }


def test_partial_indexes_match_the_design() -> None:
    companion_indexes = {index.name: index for index in Companion.__table__.indexes}
    message_indexes = {index.name: index for index in Message.__table__.indexes}
    assert "uq_companion_default" in companion_indexes
    assert "uq_message_client_id" in message_indexes
    assert companion_indexes["uq_companion_default"].unique
    assert message_indexes["uq_message_client_id"].unique


def test_check_constraints_cover_status_archive_and_message_rules() -> None:
    sql = "\n".join(_check_sql(table) for table in (User, Companion, Conversation, Message))
    assert "status = 'active'" in sql
    assert "status IN ('active', 'paused', 'archived')" in sql
    assert "status IN ('active', 'archived')" in sql
    assert "archived_at IS NOT NULL" in sql
    assert "sender_type IN ('user', 'companion', 'system')" in sql
    assert "content_type = 'text'" in sql
    assert "sequence_number >= 1" in sql
    assert "next_sequence_number >= 1" in sql


def test_message_metadata_column_is_not_the_orm_metadata_attribute() -> None:
    column = Message.__table__.c.metadata
    assert column.name == "metadata"


def test_migration_includes_model_index_names() -> None:
    migration = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(Path("alembic/versions").glob("*.py"))
    )
    for table in Base.metadata.tables.values():
        for index in table.indexes:
            assert index.name is not None
            assert index.name in migration


def test_persona_keeps_version_ownership_constraints() -> None:
    profile_names = {constraint.name for constraint in PersonaProfile.__table__.constraints}
    version_names = {constraint.name for constraint in PersonaVersion.__table__.constraints}
    assert "fk_persona_profiles_initial_version" in profile_names
    assert "fk_persona_profiles_current_version" in profile_names
    current = next(
        constraint
        for constraint in PersonaProfile.__table__.constraints
        if constraint.name == "fk_persona_profiles_current_version"
    )
    assert current.deferrable is True
    assert current.initially == "DEFERRED"
    assert "uq_persona_versions_profile_id" in version_names
    sql = _check_sql(PersonaVersion)
    assert "mbti_type IN (" in sql
    assert "version_number >= 1" in sql


def test_memory_indexes_and_unbounded_embedding_match_the_design() -> None:
    index_names = {index.name for index in Memory.__table__.indexes}
    assert index_names == {
        "ix_memories_companion_status",
        "ix_memories_companion_type_status",
        "ix_memories_companion_category",
        "ix_memories_companion_importance",
        "ix_memories_companion_updated_at",
    }
    assert MemoryEmbedding.__table__.c.embedding.type.dim is None
    migration = Path("alembic/versions/0003_memory.py").read_text(encoding="utf-8")
    assert re.search(r"vector\(\s*\d+", migration, re.IGNORECASE) is None


def test_state_version_lock_and_event_index_match_the_design() -> None:
    state_sql = _check_sql(CompanionState)
    event_sql = _check_sql(StateEvent)
    assert "version >= 1" in state_sql
    assert "emotion_changed" in event_sql
    assert "state_initialized" in event_sql
    assert "dialogue_decision" in event_sql
    assert "version_after > version_before" in event_sql
    indexes = {index.name: index for index in StateEvent.__table__.indexes}
    assert indexes["uq_state_event_version"].unique
    assert "version_after IS NOT NULL" in str(indexes["uq_state_event_version"].dialect_options["postgresql"]["where"])


def test_dialogue_actions_and_quiet_constraint_match_the_product_model() -> None:
    sql = _check_sql(DialogueDecision)
    assert "primary_action IN (" in sql
    for action in ("respond", "share", "ask", "react", "continue", "close", "quiet"):
        assert f"'{action}'" in sql
    assert "primary_action <> 'quiet'" in sql
    assert "comfort" not in sql
    index_names = {index.name for index in DialogueDecision.__table__.indexes}
    assert index_names == {
        "ix_dialogue_decisions_companion_created",
        "ix_dialogue_decisions_conversation_created",
        "ix_dialogue_decisions_status_created",
        "ix_dialogue_decisions_trigger_message",
        "uq_dialogue_decisions_result_message",
    }


def test_infrastructure_keeps_versions_and_does_not_store_prompts() -> None:
    assert "prompt" not in ModelCallLog.__table__.columns
    assert "output" not in ModelCallLog.__table__.columns
    default_index = {index.name: index for index in ModelConfig.__table__.indexes}["uq_model_config_default"]
    assert default_index.unique
    where = str(default_index.dialect_options["postgresql"]["where"])
    assert "is_enabled" in where and "is_default" in where
    constraint_names = {constraint.name for constraint in BackgroundTask.__table__.constraints}
    assert "uq_background_tasks_task_key" in constraint_names


def test_infrastructure_services_do_not_import_other_repositories() -> None:
    root = Path("app/modules/infrastructure/services")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "identity.repositories" not in source
    assert "conversation.repositories" not in source
    assert "dialogue.repositories" not in source
    assert "IdentityService" in source
    assert "ConversationService" in source
    assert "DialogueService" in source


def test_dialogue_service_does_not_import_other_repositories() -> None:
    source = Path("app/modules/dialogue/services/dialogue_service.py").read_text(encoding="utf-8")
    assert "identity.repositories" not in source
    assert "conversation.repositories" not in source
    assert "state.repositories" not in source
    assert "IdentityService" in source
    assert "ConversationService" in source
    assert "StateService" in source


def test_state_service_does_not_import_other_repositories() -> None:
    source = Path("app/modules/state/services/state_service.py").read_text(encoding="utf-8")
    assert "identity.repositories" not in source
    assert "conversation.repositories" not in source
    assert "IdentityService" in source
    assert "ConversationService" in source


def test_memory_service_does_not_import_other_repositories() -> None:
    source = Path("app/modules/memory/services/memory_service.py").read_text(encoding="utf-8")
    assert "identity.repositories" not in source
    assert "conversation.repositories" not in source
    assert "IdentityService" in source
    assert "ConversationService" in source


def test_persona_service_does_not_import_identity_repositories() -> None:
    source = Path("app/modules/persona/services/persona_service.py").read_text(encoding="utf-8")
    assert "identity.repositories" not in source
    assert "IdentityService" in source


def test_conversation_service_does_not_import_identity_repositories() -> None:
    source = Path("app/modules/conversation/services/conversation_service.py").read_text(encoding="utf-8")
    assert "identity.repositories" not in source
    assert "IdentityService" in source


def _check_sql(model: type) -> str:
    parts: list[str] = []
    for constraint in model.__table__.constraints:
        if isinstance(constraint, CheckConstraint):
            parts.append(str(constraint.sqltext))
    return "\n".join(parts)
