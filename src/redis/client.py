from redis.asyncio import Redis

from src.config import get_settings

_redis_client: Redis | None = None


def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            decode_responses=True,
        )
    return _redis_client


def set_redis(client: Redis) -> None:
    global _redis_client
    _redis_client = client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
