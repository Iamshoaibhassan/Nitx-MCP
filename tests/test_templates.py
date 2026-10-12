async def test_list_templates_without_api_key_is_rejected(async_client):
    response = await async_client.get("/templates")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_list_templates_returns_all_by_default(async_client, auth_headers):
    response = await async_client.get("/templates", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["templates"]) >= 5
    assert {"id", "name", "category"} <= body["templates"][0].keys()


async def test_list_templates_filtered_by_category(async_client, auth_headers):
    response = await async_client.get("/templates", params={"category": "sale"}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["templates"]) > 0
    assert all(t["category"] == "sale" for t in body["templates"])


async def test_list_templates_filtered_by_search_with_no_match_returns_empty_list(async_client, auth_headers):
    response = await async_client.get("/templates", params={"search": "nonexistent-xyz"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["templates"] == []
