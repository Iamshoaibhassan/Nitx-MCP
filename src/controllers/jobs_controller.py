from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis

from src.auth import caller_id, enforce_rate_limit
from src.config import Settings, get_settings
from src.models import CancelJobResponse, CreatePosterJobRequest, CreatePosterJobResponse, JobStatusResponse
from src.redis import get_redis
from src.services import JobService

router = APIRouter(prefix="/jobs", dependencies=[Depends(enforce_rate_limit)])


def get_job_service(
    redis: Redis = Depends(get_redis), settings: Settings = Depends(get_settings)
) -> JobService:
    return JobService(redis=redis, settings=settings)


@router.post("", response_model=CreatePosterJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: CreatePosterJobRequest,
    api_key: str = Depends(enforce_rate_limit),
    service: JobService = Depends(get_job_service),
) -> CreatePosterJobResponse:
    record = await service.create_job(payload, caller_id(api_key))
    return CreatePosterJobResponse(job_id=record.job_id, status=record.status)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, service: JobService = Depends(get_job_service)) -> JobStatusResponse:
    return await service.get_job(job_id)


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(job_id: str, service: JobService = Depends(get_job_service)) -> CancelJobResponse:
    record = await service.cancel_job(job_id)
    return CancelJobResponse(job_id=record.job_id, status=record.status)
