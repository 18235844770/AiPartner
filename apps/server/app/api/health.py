import logging
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text

from app.shared.database.session import get_engine
from app.shared.redis.client import ping_redis

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    api: Literal["ok"]
    database: Literal["ok", "down"]
    pgvector: Literal["ok", "down", "unknown"]
    redis: Literal["ok", "down"]


async def build_health() -> HealthResponse:
    database_ok = await _ping_database()
    pgvector: Literal["ok", "down", "unknown"] = "unknown"
    if database_ok:
        pgvector = "ok" if await _pgvector_enabled() else "down"
    redis_ok = await ping_redis()
    healthy = database_ok and redis_ok and pgvector == "ok"
    return HealthResponse(
        status="ok" if healthy else "degraded",
        api="ok",
        database="ok" if database_ok else "down",
        pgvector=pgvector,
        redis="ok" if redis_ok else "down",
    )


async def _ping_database() -> bool:
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        if isinstance(exc, OSError) or type(exc).__name__ in {"ConnectionError", "TimeoutError", "ConnectionRefusedError"}:
            logger.warning("database unavailable: %s", exc or type(exc).__name__)
            return False
        logger.exception("database health check failed")
        return False


async def _pgvector_enabled() -> bool:
    try:
        async with get_engine().connect() as connection:
            result = await connection.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            return result.scalar_one_or_none() is not None
    except Exception:
        logger.exception("pgvector health check failed")
        return False
