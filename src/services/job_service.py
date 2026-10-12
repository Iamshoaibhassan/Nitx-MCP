import hashlib
import json
import uuid
from datetime import datetime, timezone

from redis.asyncio import Redis

from src.config import Settings
from src.exceptions import ConflictError, NotFoundError, RateLimitError
from src.models import CreatePosterJobRequest, JobStatus, JobStatusResponse
from src.redis import active_jobs_key, idempotency_key, job_key
from src.utils import get_logger, log_extra
from src.worker import enqueue_job

logger = get_logger(__name__)


class JobService:
    def __init__(self, redis: Redis, settings: Settings):
        self._redis = redis
        self._settings = settings

    async def create_job(self, payload: CreatePosterJobRequest, caller_id: str) -> JobStatusResponse:
        job_id = f"job-{uuid.uuid4().hex[:16]}"

        effective_idempotency_key = payload.idempotency_key or self._derive_idempotency_key(payload)
        replay = await self._claim_or_replay_idempotency_key(effective_idempotency_key, job_id)
        if replay is not None:
            return replay

        await self._enforce_concurrency_limit(caller_id)

        now = datetime.now(timezone.utc).isoformat()
        record = {
            "job_id": job_id,
            "status": JobStatus.PROCESSING.value,
            "template_id": payload.template_id or "",
            "prompt": payload.prompt,
            "image_count": payload.image_count,
            "resolution": payload.resolution.value,
            "caller_id": caller_id,
            "images": "",
            "error": "",
            "created_at": now,
            "updated_at": now,
        }

        await self._redis.hset(job_key(job_id), mapping=record)
        await self._redis.expire(job_key(job_id), self._settings.job_record_ttl_seconds)
        await self._redis.sadd(active_jobs_key(caller_id), job_id)

        await enqueue_job(self._redis, job_id)

        logger.info(
            "Created poster job",
            extra=log_extra(job_id=job_id, image_count=payload.image_count, resolution=payload.resolution.value),
        )

        return await self._require_job_record(job_id)

    async def get_job(self, job_id: str) -> JobStatusResponse:
        return await self._require_job_record(job_id)

    async def cancel_job(self, job_id: str) -> JobStatusResponse:
        raw = await self._redis.hgetall(job_key(job_id))
        if not raw:
            raise NotFoundError(
                f"No job found with id '{job_id}'. Verify the job_id returned by create_poster_job."
            )

        current_status = raw.get("status")
        if current_status != JobStatus.PROCESSING.value:
            raise ConflictError(
                f"Job '{job_id}' already finished with status '{current_status}' and cannot be "
                "cancelled. Only jobs with status 'processing' can be cancelled.",
                details={"status": current_status},
            )

        now = datetime.now(timezone.utc).isoformat()
        await self._redis.hset(
            job_key(job_id), mapping={"status": JobStatus.CANCELLED.value, "updated_at": now}
        )
        if raw.get("caller_id"):
            await self._redis.srem(active_jobs_key(raw["caller_id"]), job_id)

        logger.info("Cancelled poster job", extra=log_extra(job_id=job_id))

        return await self._require_job_record(job_id)

    async def _enforce_concurrency_limit(self, caller_id: str) -> None:
        # Best-effort, not atomic: two requests racing between this check and the SADD in
        # create_job could both pass, briefly overshooting the limit by a small margin.
        active_count = await self._redis.scard(active_jobs_key(caller_id))
        if active_count >= self._settings.max_concurrent_jobs_per_key:
            raise RateLimitError(
                f"This API key already has {active_count} job(s) processing (limit: "
                f"{self._settings.max_concurrent_jobs_per_key}). Wait for one to finish, or cancel "
                "one, before creating another."
            )

    @staticmethod
    def _derive_idempotency_key(payload: CreatePosterJobRequest) -> str:
        canonical = json.dumps(
            {
                "template_id": payload.template_id,
                "product_image": payload.product_image,
                "background_image": payload.background_image,
                "prompt": payload.prompt,
                "image_count": payload.image_count,
                "resolution": payload.resolution.value,
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
        return f"auto-{digest}"

    async def _claim_or_replay_idempotency_key(
        self, key: str, candidate_job_id: str
    ) -> JobStatusResponse | None:
        claimed = await self._redis.set(
            idempotency_key(key), candidate_job_id, ex=self._settings.idempotency_ttl_seconds, nx=True
        )
        if claimed:
            return None

        owner_job_id = await self._redis.get(idempotency_key(key))
        existing = await self._get_job_record(owner_job_id) if owner_job_id else None
        if existing is not None:
            logger.info(
                "Idempotent replay: returning existing job for repeated idempotency_key",
                extra=log_extra(job_id=existing.job_id, idempotency_key=key),
            )
            return existing

        raise ConflictError(
            f"idempotency_key '{key}' was already used but the original job record is no longer "
            "available (it likely expired). Use a new idempotency_key to create a new job."
        )

    async def _get_job_record(self, job_id: str) -> JobStatusResponse | None:
        raw = await self._redis.hgetall(job_key(job_id))
        if not raw:
            return None

        images = json.loads(raw["images"]) if raw.get("images") else None

        return JobStatusResponse(
            job_id=raw["job_id"],
            status=JobStatus(raw["status"]),
            images=images,
            error=raw.get("error") or None,
            created_at=raw["created_at"],
            updated_at=raw["updated_at"],
        )

    async def _require_job_record(self, job_id: str) -> JobStatusResponse:
        record = await self._get_job_record(job_id)
        if record is None:
            raise NotFoundError(
                f"No job found with id '{job_id}'. It may not exist, or it may have expired after "
                f"{self._settings.job_record_ttl_seconds // 3600} hours. Create a new job if needed."
            )
        return record
