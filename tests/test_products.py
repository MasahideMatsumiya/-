"""商材モジュール テスト"""


async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "AI Marketplace"


async def test_list_products_empty(client):
    resp = await client.get("/products/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_and_get_product(client):
    payload = {
        "name": "GPT-4 プロンプトテンプレート集",
        "description": "マーケティング・営業向け高品質プロンプト50選",
        "short_description": "AIプロンプト集 50選",
        "category": "prompt",
        "price_usd": 9.99,
        "tags": "gpt4,marketing,sales",
        "ai_models": "GPT-4,Claude",
    }
    resp = await client.post("/products/", json=payload)
    assert resp.status_code == 200
    product = resp.json()
    assert product["name"] == payload["name"]
    assert product["price_usd"] == 9.99
    assert product["slug"] == "gpt-4"
