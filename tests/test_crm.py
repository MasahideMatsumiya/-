"""顧客管理 テスト"""


async def test_create_customer(client):
    payload = {"email": "test@example.com", "name": "Test User", "country": "JP"}
    resp = await client.post("/crm/customers", json=payload)
    assert resp.status_code == 200
    customer = resp.json()
    assert customer["email"] == "test@example.com"
    assert customer["segment"] == "new"


async def test_duplicate_customer(client):
    payload = {"email": "dup@example.com", "name": "Dup User"}
    await client.post("/crm/customers", json=payload)
    resp = await client.post("/crm/customers", json=payload)
    assert resp.status_code == 409


async def test_segment_summary(client):
    resp = await client.get("/crm/segments/summary")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
