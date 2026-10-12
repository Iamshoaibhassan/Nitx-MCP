import time

from fastapi import Request

from src.utils import get_logger, log_extra

logger = get_logger(__name__)


async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "Request handled",
        extra=log_extra(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        ),
    )
    return response
