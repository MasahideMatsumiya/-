"""取引法コンプライアンス テスト"""


async def test_tokushoho(client):
    resp = await client.get("/compliance/tokushoho")
    assert resp.status_code == 200
    data = resp.json()
    assert "特定商取引法" in data["title"]
    assert "return_policy" in data
    assert "payment_methods" in data
