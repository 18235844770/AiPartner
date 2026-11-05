import logging

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


async def ping_redis() -> bool:
    settings = get_settings()
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry=Retry(NoBackoff(), 0),
    )
    try:
        return bool(await client.ping())
    except Exception as exc:
        if _is_connectivity_error(exc):
            logger.warning("redis unavailable: %s", exc or type(exc).__name__)
            return False
        logger.exception("redis health check failed")
        return False
    finally:
        await client.aclose()


def _is_connectivity_error(exc: BaseException) -> bool:
    if isinstance(exc, (OSError, TimeoutError)):
        return True
    return type(exc).__name__ in {"ConnectionError", "TimeoutError", "ConnectionRefusedError"}
