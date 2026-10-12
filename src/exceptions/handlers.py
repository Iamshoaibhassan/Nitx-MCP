import redis.exceptions
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.exceptions.custom_exceptions import AppException
from src.utils import build_error_body, get_logger, log_extra

logger = get_logger(__name__)

_REDIS_ERROR_RESPONSES = {
    redis.exceptions.TimeoutError: (504, "UPSTREAM_TIMEOUT", "The job store took too long to respond. Wait a moment and retry the same request."),
    redis.exceptions.ConnectionError: (503, "UPSTREAM_UNAVAILABLE", "The job store is temporarily unavailable. Wait a few seconds and retry."),
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            exc.message,
            extra=log_extra(path=str(request.url.path), method=request.method, error_code=exc.error_code),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_body(exc.error_code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning(
            "Request validation failed",
            extra=log_extra(path=str(request.url.path), method=request.method),
        )
        return JSONResponse(
            status_code=400,
            content=build_error_body(
                "VALIDATION_ERROR",
                "The request body does not match the expected schema. Check required fields and types.",
                {"errors": exc.errors()},
            ),
        )

    async def handle_redis_error(request: Request, exc: Exception) -> JSONResponse:
        status_code, error_code, message = _REDIS_ERROR_RESPONSES[type(exc)]
        logger.error(
            "Redis call failed",
            exc_info=exc,
            extra=log_extra(path=str(request.url.path), method=request.method, error_code=error_code),
        )
        return JSONResponse(status_code=status_code, content=build_error_body(error_code, message))

    for redis_exception_type in _REDIS_ERROR_RESPONSES:
        app.add_exception_handler(redis_exception_type, handle_redis_error)

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            exc_info=exc,
            extra=log_extra(path=str(request.url.path), method=request.method),
        )
        return JSONResponse(
            status_code=500,
            content=build_error_body(
                "INTERNAL_ERROR",
                "An unexpected error occurred. Retry the request; if it keeps failing, contact support.",
            ),
        )
