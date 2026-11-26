import logging
import shutil
import uuid
from contextlib import AsyncExitStack

from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool

from app.config.settings import get_settings
from app.modules.identity.repositories.models import Companion, User
from app.shared.database.companion_lock import try_companion_lock
from app.shared.database.session import get_session_factory


logger = logging.getLogger(__name__)


def _remove_media(companion_id: uuid.UUID) -> None:
    storage = get_settings().audio_storage_dir.resolve()
    for dirname in ("voices", "generated"):
        target = storage / dirname / str(companion_id)
        if target.resolve() != target:
            raise ValueError("音频存储目录指向其他位置")
        if target.is_dir():
            shutil.rmtree(target)


class AccountErasureService:
    async def process_waiting(self, limit: int = 20) -> None:
        async with get_session_factory()() as session:
            ids = list(await session.scalars(select(User.id).where(User.status == "deleting").limit(limit)))
        for user_id in ids:
            try:
                await self.process(user_id)
            except Exception as exc:
                logger.error("account deletion pending for %s (%s)", user_id, type(exc).__name__)

    async def process(self, user_id: uuid.UUID) -> None:
        factory = get_session_factory()
        async with factory() as session:
            owners = list(await session.scalars(
                select(Companion.id).join(User, User.id == Companion.owner_user_id)
                .where(User.id == user_id, User.status == "deleting").order_by(Companion.id),
            ))
        async with AsyncExitStack() as locks:
            for companion_id in owners:
                for scope in ("dialogue", "audio"):
                    if not await locks.enter_async_context(try_companion_lock(companion_id, scope=scope)):
                        return
            for companion_id in owners:
                await run_in_threadpool(_remove_media, companion_id)
            async with factory() as session, session.begin():
                await session.execute(text("SELECT erase_companion_account(:user_id)"), {"user_id": user_id})
