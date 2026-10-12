async def test_missing_api_key_returns_401(async_client):
    response = await async_client.get("/jobs/job-does-not-matter")
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert "X-API-Key" in body["error"]["message"]


async def test_invalid_api_key_returns_401(async_client):
    response = await async_client.get("/jobs/job-does-not-matter", headers={"X-API-Key": "wrong-key"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_api_key_is_never_echoed_back_in_responses(async_client, auth_headers):
    response = await async_client.get("/templates", headers=auth_headers)
    assert "test-api-key" not in response.text
