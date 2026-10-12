from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import get_settings
from src.controllers import jobs_router, templates_router
from src.exceptions import register_exception_handlers
from src.middleware import log_requests
from src.redis import close_redis, get_redis
from src.utils import configure_logging, get_logger, log_extra
from src.worker import ensure_group

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_group(get_redis())
    logger.info("Service starting up", extra=log_extra(app=settings.app_name))
    yield
    await close_redis()
    logger.info("Service shutting down")


app = FastAPI(
    title="Nitx Poster Generation Service (Mock)",
    version="1.0.0",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.middleware("http")(log_requests)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok"}


app.include_router(templates_router)
app.include_router(jobs_router)
