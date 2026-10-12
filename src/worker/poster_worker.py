import asyncio
import json
import random
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from src.config import Settings, get_settings
from src.models import GeneratedImage, JobStatus, Resolution
from src.redis import active_jobs_key, get_redis, job_key
from src.utils import configure_logging, get_logger, log_extra
from src.worker.stream import GROUP_NAME, STREAM_KEY, ensure_group

logger = get_logger(__name__)

_FAILURE_MESSAGES = [
    "The rendering engine failed to compose the product and background layers for this request.",
    "The upstream image model timed out while generating the poster.",
    "An internal rendering error occurred while applying the requested template.",
]


async def render_job(redis: Redis, settings: Settings, job_id: str) -> None:
    raw = await redis.hgetall(job_key(job_id))
    if not raw or raw.get("status") != JobStatus.PROCESSING.value:
        return

    image_count = int(raw["image_count"])
    resolution = Resolution(raw["resolution"])
    owner = raw.get("caller_id", "")

    duration = random.uniform(settings.job_min_duration_seconds, settings.job_max_duration_seconds)
    elapsed = 0.0
    while elapsed < duration:
        step = min(settings.job_poll_interval_seconds, duration - elapsed)
        await asyncio.sleep(step)
        elapsed += step

        current_status = await redis.hget(job_key(job_id), "status")
        if current_status != JobStatus.PROCESSING.value:
            await _release_slot(redis, owner, job_id)
            return

    if random.random() < settings.job_failure_rate:
        await _mark_failed(redis, job_id, owner, random.choice(_FAILURE_MESSAGES))
        return

    images = await _generate_images(job_id, image_count, resolution)
    await _mark_completed(redis, job_id, owner, images)


async def _generate_images(job_id: str, image_count: int, resolution: Resolution) -> list[GeneratedImage]:
    async def build_one(index: int) -> GeneratedImage:
        return GeneratedImage(
            id=f"{job_id}-img-{index}",
            url=f"https://mock-cdn.nitx.ai/posters/{job_id}/{index}.png",
            resolution=resolution,
        )

    return list(await asyncio.gather(*(build_one(i) for i in range(1, image_count + 1))))


async def _mark_completed(redis: Redis, job_id: str, owner: str, images: list[GeneratedImage]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(
        job_key(job_id),
        mapping={
            "status": JobStatus.COMPLETED.value,
            "images": json.dumps([image.model_dump(mode="json") for image in images]),
            "updated_at": now,
        },
    )
    await _release_slot(redis, owner, job_id)


async def _mark_failed(redis: Redis, job_id: str, owner: str, message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await redis.hset(
        job_key(job_id),
        mapping={"status": JobStatus.FAILED.value, "error": message, "updated_at": now},
    )
    await _release_slot(redis, owner, job_id)


async def _release_slot(redis: Redis, owner: str, job_id: str) -> None:
    if owner:
        await redis.srem(active_jobs_key(owner), job_id)


async def _process_entry(redis: Redis, settings: Settings, entry_id: str, fields: dict) -> None:
    job_id = fields["job_id"]
    try:
        await render_job(redis, settings, job_id)
    except Exception as exc:
        logger.error("Worker failed to render job", exc_info=exc, extra=log_extra(job_id=job_id))
    finally:
        await redis.xack(STREAM_KEY, GROUP_NAME, entry_id)


async def _reclaim_stale_entries(redis: Redis, settings: Settings, consumer_name: str) -> None:
    _cursor, claimed, _deleted = await redis.xautoclaim(
        STREAM_KEY,
        GROUP_NAME,
        consumer_name,
        min_idle_time=settings.job_stale_claim_seconds * 1000,
        start_id="0",
    )
    for entry_id, fields in claimed:
        await _process_entry(redis, settings, entry_id, fields)


async def run_worker() -> None:
    settings = get_settings()
    redis = get_redis()
    await ensure_group(redis)

    consumer_name = f"worker-{uuid.uuid4().hex[:8]}"
    logger.info("Worker started", extra=log_extra(consumer=consumer_name))

    while True:
        try:
            await _reclaim_stale_entries(redis, settings, consumer_name)

            response = await redis.xreadgroup(
                GROUP_NAME, consumer_name, {STREAM_KEY: ">"}, count=1, block=5000
            )
            for _stream_name, messages in response:
                for entry_id, fields in messages:
                    await _process_entry(redis, settings, entry_id, fields)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Worker loop iteration failed, retrying", exc_info=exc)
            await ensure_group(redis)
            await asyncio.sleep(1)


if __name__ == "__main__":
    configure_logging("INFO")
    asyncio.run(run_worker())
