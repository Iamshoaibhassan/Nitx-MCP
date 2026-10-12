from fastapi import Depends
from redis.asyncio import Redis

from src.auth.api_key import caller_id, verify_api_key
from src.config import Settings, get_settings
from src.exceptions import RateLimitError
from src.redis import get_redis, rate_limit_key


async def enforce_rate_limit(
    api_key: str = Depends(verify_api_key),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> str:
    key = rate_limit_key(caller_id(api_key))
    request_count = await redis.incr(key)
    if request_count == 1:
        await redis.expire(key, settings.rate_limit_window_seconds)

    if request_count > settings.rate_limit_requests_per_window:
        raise RateLimitError(
            f"Rate limit exceeded: max {settings.rate_limit_requests_per_window} requests per "
            f"{settings.rate_limit_window_seconds}s for this API key. Wait before retrying."
        )

    return api_key
