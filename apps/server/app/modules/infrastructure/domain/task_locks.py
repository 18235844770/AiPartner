import uuid


def task_lock_keys(task_id: uuid.UUID) -> tuple[int, int]:
    return (
        int.from_bytes(task_id.bytes[:4], "big", signed=True),
        int.from_bytes(task_id.bytes[4:8], "big", signed=True),
    )
