from src.config import get_settings
from tests.test_jobs import _valid_payload


async def test_requests_beyond_rate_limit_window_are_rejected(async_client, auth_headers):
    limit = get_settings().rate_limit_requests_per_window

    for _ in range(limit):
        response = await async_client.get("/templates", headers=auth_headers)
        assert response.status_code == 200

    response = await async_client.get("/templates", headers=auth_headers)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


async def test_create_job_rejects_once_concurrency_limit_is_reached(async_client, auth_headers):
    limit = get_settings().max_concurrent_jobs_per_key

    for i in range(limit):
        response = await async_client.post(
            "/jobs", json=_valid_payload(prompt=f"Poster variant {i}"), headers=auth_headers
        )
        assert response.status_code == 202

    response = await async_client.post(
        "/jobs", json=_valid_payload(prompt="One too many"), headers=auth_headers
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
