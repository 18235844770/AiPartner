from enum import StrEnum


class AudioTaskType(StrEnum):
    ASR = "asr"
    TTS = "tts"


class AudioTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AudioEngine(StrEnum):
    COSYVOICE3 = "cosyvoice3"
    STUB = "stub"
