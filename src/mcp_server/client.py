import httpx
from mcp.server.mcpserver.exceptions import ToolError

from src.config import get_settings
from src.utils import get_logger, log_extra

logger = get_logger(__name__)


class BackendError(ToolError):
    def __init__(self, message: str, error_code: str = "BACKEND_ERROR", status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code


def _extract_error_message(response: httpx.Response) -> tuple[str, str]:
    try:
        body = response.json()
        error = body.get("error", {})
        code = error.get("code", "BACKEND_ERROR")
        message = error.get("message", response.text)
        return code, message
    except ValueError:
        return "BACKEND_ERROR", f"Backend returned HTTP {response.status_code} with a non-JSON body."


class BackendClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        settings = get_settings()
        self._base_url = settings.mcp_backend_base_url.rstrip("/")
        self._api_key = settings.api_key
        self._timeout = settings.mcp_http_timeout_seconds
        self._max_retries = settings.mcp_http_max_retries
        self._transport = transport

    async def request(self, method: str, path: str, json_body: dict | None = None, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        headers = {"X-API-Key": self._api_key}

        if json_body is not None:
            json_body = {k: v for k, v in json_body.items() if v is not None}
        if params is not None:
            params = {k: v for k, v in params.items() if v is not None}

        timed_out = False

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    response = await client.request(
                        method, url, headers=headers, json=json_body, params=params
                    )

                if response.status_code >= 400:
                    code, message = _extract_error_message(response)
                    raise BackendError(message, error_code=code, status_code=response.status_code)

                return response.json()

            except BackendError:
                raise
            except httpx.TimeoutException:
                timed_out = True
                logger.warning(
                    "Backend request timed out, will retry if attempts remain",
                    extra=log_extra(method=method, path=path, attempt=attempt),
                )
                continue
            except httpx.ConnectError:
                timed_out = False
                logger.warning(
                    "Backend connection failed, will retry if attempts remain",
                    extra=log_extra(method=method, path=path, attempt=attempt),
                )
                continue

        logger.error(
            "Backend request exhausted all retries",
            extra=log_extra(method=method, path=path, timed_out=timed_out),
        )

        if timed_out:
            raise BackendError(
                "The poster service took too long to respond after multiple attempts. Wait a few "
                "seconds and try again; if you were creating a job, retry with the same "
                "idempotency_key to avoid creating a duplicate.",
                error_code="UPSTREAM_TIMEOUT",
                status_code=504,
            )

        raise BackendError(
            "The poster service could not be reached after multiple attempts. It may be "
            "temporarily down. Wait a few seconds and try again.",
            error_code="UPSTREAM_UNAVAILABLE",
        )
