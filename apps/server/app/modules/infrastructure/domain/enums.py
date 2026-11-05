from enum import StrEnum


class ModelProvider(StrEnum):
    DEEPSEEK = "deepseek"


class ModelConfigKey(StrEnum):
    CONVERSATION = "conversation_model"
    DECISION = "decision_model"
    MEMORY = "memory_model"
    EMBEDDING = "embedding_model"


class ModelTaskType(StrEnum):
    CONVERSATION = "conversation"
    DECISION = "decision"
    MEMORY = "memory"
    EMBEDDING = "embedding"


class ModelCallStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class BackgroundTaskType(StrEnum):
    MEMORY_EXTRACT = "memory_extract"
    MEMORY_EVALUATE = "memory_evaluate"
    MEMORY_EMBEDDING = "memory_embedding"
    MEMORY_RELATION = "memory_relation"
    MEMORY_SUMMARIZE = "memory_summarize"
    STATE_MAINTENANCE = "state_maintenance"
    PROACTIVE_CHECK = "proactive_check"


class BackgroundTaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


CONFIG_TASK_TYPES = {
    ModelConfigKey.CONVERSATION: ModelTaskType.CONVERSATION,
    ModelConfigKey.DECISION: ModelTaskType.DECISION,
    ModelConfigKey.MEMORY: ModelTaskType.MEMORY,
    ModelConfigKey.EMBEDDING: ModelTaskType.EMBEDDING,
}
