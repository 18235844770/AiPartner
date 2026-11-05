from enum import StrEnum


class MemoryType(StrEnum):
    WORKING = "working"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"


class MemoryStatus(StrEnum):
    CANDIDATE = "candidate"
    PENDING = "pending"
    ACTIVE = "active"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class MemoryOrigin(StrEnum):
    USER_EXPLICIT = "user_explicit"
    USER_BEHAVIOR = "user_behavior"
    AI_INFERENCE = "ai_inference"
    AI_INTEREST = "ai_interest"
    SYSTEM_GENERATED = "system_generated"


class MemoryChangeType(StrEnum):
    CREATE = "create"
    SUPPLEMENT = "supplement"
    CORRECT = "correct"
    UPDATE = "update"
    MERGE = "merge"


class MemorySourceType(StrEnum):
    MESSAGE = "message"
    MEMORY = "memory"
    SYSTEM = "system"


class MemorySourceRole(StrEnum):
    EVIDENCE = "evidence"
    CONTEXT = "context"
    CORRECTION = "correction"


class MemoryRelationType(StrEnum):
    RELATED_TO = "related_to"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"
    CAUSED_BY = "caused_by"
    PART_OF = "part_of"


class EmbeddingStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
