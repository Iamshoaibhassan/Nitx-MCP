import pytest
from httpx import ASGITransport

import src.mcp_server.server as mcp_server_module
from src.main import app
from src.mcp_server import BackendClient
from tests.test_jobs import _valid_payload


@pytest.fixture
def mcp_tools(redis_client, monkeypatch):
    original_client = mcp_server_module._client
    mcp_server_module._client = BackendClient(transport=ASGITransport(app=app))
    yield mcp_server_module
    mcp_server_module._client = original_client


async def test_mcp_list_templates_tool(mcp_tools):
    result = await mcp_tools.list_templates()
    assert "templates" in result
    assert len(result["templates"]) > 0


async def test_mcp_create_and_poll_job_status_tool(mcp_tools, worker):
    payload = _valid_payload()
    created = await mcp_tools.create_poster_job(
        product_image=payload["product_image"],
        background_image=payload["background_image"],
        prompt=payload["prompt"],
        image_count=payload["image_count"],
        resolution=payload["resolution"],
    )
    assert created["status"] == "processing"
    job_id = created["job_id"]

    final = None
    for _ in range(200):
        final = await mcp_tools.get_job_status(job_id=job_id)
        if final["status"] != "processing":
            break
        import asyncio

        await asyncio.sleep(0.02)

    assert final["status"] in {"completed", "failed"}


async def test_mcp_get_job_status_unknown_job_raises_actionable_error(mcp_tools):
    with pytest.raises(Exception) as exc_info:
        await mcp_tools.get_job_status(job_id="job-unknown")
    assert "job-unknown" in str(exc_info.value)


async def test_mcp_cancel_job_tool(mcp_tools):
    payload = _valid_payload()
    created = await mcp_tools.create_poster_job(
        product_image=payload["product_image"],
        background_image=payload["background_image"],
        prompt=payload["prompt"],
        image_count=payload["image_count"],
        resolution=payload["resolution"],
    )

    cancelled = await mcp_tools.cancel_job(job_id=created["job_id"])
    assert cancelled["status"] == "cancelled"


async def test_mcp_tool_schema_exposes_constraints_for_llm(mcp_tools):
    tools = await mcp_tools.mcp.list_tools()
    create_tool = next(t for t in tools if t.name == "create_poster_job")

    schema = create_tool.input_schema
    assert schema["properties"]["image_count"]["minimum"] == 1
    assert schema["properties"]["image_count"]["maximum"] == 4
    assert schema["properties"]["prompt"]["maxLength"] == 500
    assert set(schema["properties"]["resolution"]["enum"]) == {"1k", "2k"}
    assert create_tool.description
