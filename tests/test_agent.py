"""AIエージェント専用API テスト"""
import json

import pytest

from src.crm.models import AgentFramework, Customer
from src.products.models import Product, ProductCategory, ProductStatus


@pytest.fixture
async def active_product(session):
    p = Product(
        slug="agent-test-product",
        name="Agent Test Prompt",
        description="desc",
        short_description="short",
        category=ProductCategory.PROMPT,
        status=ProductStatus.ACTIVE,
        price_usd=10.0,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


@pytest.fixture
async def registered_agent(client):
    """エージェントを登録してAPIキーを返す"""
    resp = await client.post("/agent/register", json={
        "email": "agent_bot@example.com",
        "name": "TestBot",
        "framework": "langchain",
        "callback_url": None,
        "capabilities": ["text_gen", "code"],
    })
    assert resp.status_code == 200
    return resp.json()


# ---------- 登録 ----------

async def test_agent_register(client):
    resp = await client.post("/agent/register", json={
        "email": "bot1@example.com",
        "name": "Bot1",
        "framework": "crewai",
        "callback_url": "https://example.com/webhook",
        "capabilities": ["search", "code"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["api_key"].startswith("ak_live_")
    assert "key_prefix" in data
    assert data["customer_id"] > 0


async def test_agent_register_duplicate_email(client, registered_agent):
    resp = await client.post("/agent/register", json={
        "email": "agent_bot@example.com",
        "name": "Duplicate",
        "framework": "unknown",
    })
    assert resp.status_code == 409


# ---------- カタログ ----------

async def test_catalog_no_auth(client, active_product):
    """APIキーなしでもカタログ閲覧可能"""
    resp = await client.get("/agent/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["schema_version"] == "1.0"
    assert len(data["items"]) >= 1
    # 機械可読メタデータが含まれる
    item = data["items"][0]
    assert "machine_metadata" in item
    assert "checkout_endpoint" in item["machine_metadata"]


async def test_catalog_search(client, active_product):
    resp = await client.get("/agent/catalog?search=Agent+Test")
    assert resp.status_code == 200
    data = resp.json()
    assert any("Agent Test" in i["name"] for i in data["items"])


async def test_catalog_category_filter(client, active_product):
    resp = await client.get("/agent/catalog?category=prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert all(i["category"] == "prompt" for i in data["items"])


# ---------- 認証付きエンドポイント ----------

async def test_agent_profile(client, registered_agent):
    api_key = registered_agent["api_key"]
    resp = await client.get("/agent/me", headers={"X-Api-Key": api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_framework"] == "langchain"
    assert "stats" in data
    assert data["stats"]["total_orders"] == 0


async def test_agent_profile_invalid_key(client):
    resp = await client.get("/agent/me", headers={"X-Api-Key": "ak_live_invalid"})
    assert resp.status_code == 401


# ---------- チェックアウト ----------

async def test_agent_checkout(client, registered_agent, active_product):
    api_key = registered_agent["api_key"]
    resp = await client.post(
        "/agent/checkout",
        json={"product_id": active_product.id},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order_number"].startswith("ORD-")
    assert data["product_name"] == "Agent Test Prompt"
    assert data["total_usd"] > 0
    assert "/marketplace/download/" in data["download_url"]
    assert data["delivery_status"] in ("delivered", "failed", "webhook_sent")


async def test_agent_checkout_updates_stats(client, registered_agent, active_product):
    api_key = registered_agent["api_key"]
    await client.post(
        "/agent/checkout",
        json={"product_id": active_product.id},
        headers={"X-Api-Key": api_key},
    )
    profile = await client.get("/agent/me", headers={"X-Api-Key": api_key})
    stats = profile.json()["stats"]
    assert stats["total_orders"] == 1
    assert stats["total_spent_usd"] > 0


async def test_agent_checkout_invalid_product(client, registered_agent):
    api_key = registered_agent["api_key"]
    resp = await client.post(
        "/agent/checkout",
        json={"product_id": 99999},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 404


# ---------- キーローテーション ----------

async def test_rotate_key(client, registered_agent):
    old_key = registered_agent["api_key"]
    resp = await client.post("/agent/rotate-key", headers={"X-Api-Key": old_key})
    assert resp.status_code == 200
    new_key = resp.json()["api_key"]
    assert new_key != old_key
    assert new_key.startswith("ak_live_")

    # 旧キーは無効
    resp_old = await client.get("/agent/me", headers={"X-Api-Key": old_key})
    assert resp_old.status_code == 401

    # 新キーは有効
    resp_new = await client.get("/agent/me", headers={"X-Api-Key": new_key})
    assert resp_new.status_code == 200


# ---------- MCP マニフェスト ----------

async def test_mcp_manifest(client, active_product):
    resp = await client.get("/agent/mcp-manifest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema"] == "mcp/1.0"
    assert "tools" in data
    assert "resources" in data
    assert data["auth"]["type"] == "api_key"
    # 商材がtoolとして含まれる
    assert any(t["product_id"] == active_product.id for t in data["tools"])
