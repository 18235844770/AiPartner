"""把一次记忆或关注变化排进主动检查。相同事件只排一次。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.infrastructure.api.schemas import CreateBackgroundTaskRequest
from app.modules.infrastructure.domain.enums import BackgroundTaskType
from app.modules.infrastructure.services.background_task_service import BackgroundTaskService

_PREFIX = "proactive-check:event:"


def proactive_event_task_key(event_key: str) -> str:
    cleaned = event_key.strip()
    if not cleaned:
        raise ValueError("主动检查事件标识不能为空")
    key = f"{_PREFIX}{cleaned}"
    if len(key) > 128:
        raise ValueError("主动检查事件标识过长")
    return key


async def schedule_proactive_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    companion_id: uuid.UUID,
    event_key: str,
    tasks: BackgroundTaskService | None = None,
) -> bool:
    result = await (tasks or BackgroundTaskService()).create(
        session,
        CreateBackgroundTaskRequest(
            user_id=user_id,
            companion_id=companion_id,
            task_type=BackgroundTaskType.PROACTIVE_CHECK,
            task_key=proactive_event_task_key(event_key),
            queue_name="dialogue",
            payload={"user_id": str(user_id)},
            max_retries=2,
            scheduled_at=datetime.now(UTC),
        ),
    )
    return result.created
