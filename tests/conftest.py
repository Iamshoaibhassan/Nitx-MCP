import asyncio
import contextlib

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from src.config import get_settings
from src.main import app
from src.models import JobStatus
from src.redis import set_redis
from src.utils import ENV
from src.worker.poster_worker import run_worker

ENV["REDIS_DB"] = "15"
ENV["JOB_MIN_DURATION_SECONDS"] = "0.05"
ENV["JOB_MAX_DURATION_SECONDS"] = "0.15"


@pytest.fixture
async def redis_client():
    settings = get_settings()
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=True,
    )
    await client.flushdb()
    set_redis(client)
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def async_client(redis_client):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def auth_headers():
    return {"X-API-Key": ENV["API_KEY"]}


@pytest.fixture
async def worker(redis_client):
    task = asyncio.create_task(run_worker())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def poll_job_until_terminal(client: AsyncClient, headers: dict, job_id: str, timeout: float = 5.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        response = await client.get(f"/jobs/{job_id}", headers=headers)
        body = response.json()
        if body["status"] != JobStatus.PROCESSING.value:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not reach a terminal state within {timeout}s")
