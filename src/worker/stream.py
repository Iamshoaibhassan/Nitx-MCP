from redis.asyncio import Redis
from redis.exceptions import ResponseError

STREAM_KEY = "poster:jobs:stream"
GROUP_NAME = "poster:workers"


async def ensure_group(redis: Redis) -> None:
    try:
        await redis.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def enqueue_job(redis: Redis, job_id: str) -> None:
    await redis.xadd(STREAM_KEY, {"job_id": job_id})
