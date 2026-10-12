import pytest

from tests.conftest import poll_job_until_terminal


def _valid_payload(**overrides) -> dict:
    payload = {
        "product_image": "https://example.com/product.png",
        "background_image": "https://example.com/background.png",
        "prompt": "A vibrant summer sale poster with bold red typography",
        "image_count": 2,
        "resolution": "1k",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def force_job_success(monkeypatch):
    monkeypatch.setattr("src.worker.poster_worker.random.random", lambda: 0.99)


@pytest.fixture
def force_job_failure(monkeypatch):
    monkeypatch.setattr("src.worker.poster_worker.random.random", lambda: 0.0)


async def test_create_job_rejects_prompt_over_500_characters(async_client, auth_headers):
    response = await async_client.post(
        "/jobs", json=_valid_payload(prompt="x" * 501), headers=auth_headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_create_job_rejects_image_count_out_of_range(async_client, auth_headers):
    response = await async_client.post(
        "/jobs", json=_valid_payload(image_count=5), headers=auth_headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_create_job_returns_processing_immediately(async_client, auth_headers):
    response = await async_client.post("/jobs", json=_valid_payload(), headers=auth_headers)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["job_id"].startswith("job-")


async def test_job_completes_successfully_with_requested_image_count(
    async_client, auth_headers, worker, force_job_success
):
    create_response = await async_client.post(
        "/jobs", json=_valid_payload(image_count=3, resolution="2k"), headers=auth_headers
    )
    job_id = create_response.json()["job_id"]

    final = await poll_job_until_terminal(async_client, auth_headers, job_id)

    assert final["status"] == "completed"
    assert len(final["images"]) == 3
    assert all(img["resolution"] == "2k" for img in final["images"])
    assert final["error"] is None


async def test_job_reports_failure_with_actionable_error_message(
    async_client, auth_headers, worker, force_job_failure
):
    create_response = await async_client.post("/jobs", json=_valid_payload(), headers=auth_headers)
    job_id = create_response.json()["job_id"]

    final = await poll_job_until_terminal(async_client, auth_headers, job_id)

    assert final["status"] == "failed"
    assert final["images"] is None
    assert isinstance(final["error"], str) and len(final["error"]) > 0


async def test_get_job_status_for_unknown_job_returns_404(async_client, auth_headers):
    response = await async_client.get("/jobs/job-does-not-exist", headers=auth_headers)
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "job-does-not-exist" in body["error"]["message"]


async def test_cancel_job_while_processing_succeeds(async_client, auth_headers):
    create_response = await async_client.post("/jobs", json=_valid_payload(), headers=auth_headers)
    job_id = create_response.json()["job_id"]

    cancel_response = await async_client.post(f"/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    status_response = await async_client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert status_response.json()["status"] == "cancelled"


async def test_cancel_job_after_completion_returns_conflict(
    async_client, auth_headers, worker, force_job_success
):
    create_response = await async_client.post("/jobs", json=_valid_payload(), headers=auth_headers)
    job_id = create_response.json()["job_id"]
    await poll_job_until_terminal(async_client, auth_headers, job_id)

    cancel_response = await async_client.post(f"/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancel_response.status_code == 409
    assert cancel_response.json()["error"]["code"] == "CONFLICT"


async def test_cancel_unknown_job_returns_404(async_client, auth_headers):
    response = await async_client.post("/jobs/job-does-not-exist/cancel", headers=auth_headers)
    assert response.status_code == 404
