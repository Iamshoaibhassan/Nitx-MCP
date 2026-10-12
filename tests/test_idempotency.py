from tests.test_jobs import _valid_payload


async def test_explicit_idempotency_key_dedupes_retry(async_client, auth_headers):
    payload = _valid_payload(idempotency_key="retry-key-123")

    first = await async_client.post("/jobs", json=payload, headers=auth_headers)
    second = await async_client.post("/jobs", json=payload, headers=auth_headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


async def test_auto_derived_key_dedupes_identical_payload_without_explicit_key(async_client, auth_headers):
    payload = _valid_payload()

    first = await async_client.post("/jobs", json=payload, headers=auth_headers)
    second = await async_client.post("/jobs", json=payload, headers=auth_headers)

    assert first.json()["job_id"] == second.json()["job_id"]


async def test_different_payloads_without_explicit_key_create_distinct_jobs(async_client, auth_headers):
    first = await async_client.post("/jobs", json=_valid_payload(prompt="Poster A"), headers=auth_headers)
    second = await async_client.post("/jobs", json=_valid_payload(prompt="Poster B"), headers=auth_headers)

    assert first.json()["job_id"] != second.json()["job_id"]


async def test_different_explicit_idempotency_keys_create_distinct_jobs_for_same_payload(
    async_client, auth_headers
):
    payload_a = _valid_payload(idempotency_key="key-a")
    payload_b = _valid_payload(idempotency_key="key-b")

    first = await async_client.post("/jobs", json=payload_a, headers=auth_headers)
    second = await async_client.post("/jobs", json=payload_b, headers=auth_headers)

    assert first.json()["job_id"] != second.json()["job_id"]


async def test_idempotency_key_with_expired_job_record_returns_conflict(async_client, auth_headers, redis_client):
    payload = _valid_payload(idempotency_key="orphaned-key")

    create_response = await async_client.post("/jobs", json=payload, headers=auth_headers)
    job_id = create_response.json()["job_id"]

    await redis_client.delete(f"poster:job:{job_id}")

    retry_response = await async_client.post("/jobs", json=payload, headers=auth_headers)
    assert retry_response.status_code == 409
    assert retry_response.json()["error"]["code"] == "CONFLICT"
