import asyncio

import httpx
import pytest

from src.mcp_server import BackendClient, BackendError
from src.utils import ENV


def test_backend_client_retries_on_timeout_then_succeeds():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            raise httpx.TimeoutException("simulated timeout")
        return httpx.Response(200, json={"ok": True})

    client = BackendClient(transport=httpx.MockTransport(handler))

    result = asyncio.run(client.request("GET", "/whatever"))

    assert result == {"ok": True}
    assert calls["count"] == 2


def test_backend_client_raises_timeout_error_after_exhausting_retries(monkeypatch):
    monkeypatch.setitem(ENV, "MCP_HTTP_MAX_RETRIES", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    client = BackendClient(transport=httpx.MockTransport(handler))

    with pytest.raises(BackendError) as exc_info:
        asyncio.run(client.request("GET", "/whatever"))

    message = str(exc_info.value).lower()
    assert "try again" in message or "retry" in message
    assert exc_info.value.error_code == "UPSTREAM_TIMEOUT"
    assert exc_info.value.status_code == 504


def test_backend_client_raises_unavailable_error_on_connection_failure(monkeypatch):
    monkeypatch.setitem(ENV, "MCP_HTTP_MAX_RETRIES", "1")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection refused")

    client = BackendClient(transport=httpx.MockTransport(handler))

    with pytest.raises(BackendError) as exc_info:
        asyncio.run(client.request("GET", "/whatever"))

    assert exc_info.value.error_code == "UPSTREAM_UNAVAILABLE"


def test_backend_client_translates_error_body_from_backend():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"success": False, "error": {"code": "NOT_FOUND", "message": "job not found"}}
        )

    client = BackendClient(transport=httpx.MockTransport(handler))

    with pytest.raises(BackendError) as exc_info:
        asyncio.run(client.request("GET", "/whatever"))

    assert exc_info.value.error_code == "NOT_FOUND"
    assert exc_info.value.status_code == 404
    assert exc_info.value.message == "job not found"


def test_backend_client_none_values_are_stripped_from_payload_and_params():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = BackendClient(transport=httpx.MockTransport(handler))

    asyncio.run(
        client.request(
            "POST", "/whatever", json_body={"a": 1, "b": None}, params={"x": None, "y": "z"}
        )
    )

    assert "x=" not in captured["url"]
    assert "y=z" in captured["url"]
    assert b"b" not in captured["body"]
