import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import get_settings


@asynccontextmanager
async def try_companion_lock(companion_id: uuid.UUID, *, scope: str = "dialogue") -> AsyncIterator[bool]:
    """The database releases this session lock when the worker connection closes."""
    key = int.from_bytes(hashlib.blake2b(scope.encode() + companion_id.bytes, digest_size=8).digest(), "big", signed=True)
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            acquired = await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            await connection.commit()
            yield bool(acquired)
    finally:
        await engine.dispose()
