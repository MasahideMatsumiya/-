"""成長KPI・一括商材・レコメンド テスト"""
from datetime import datetime, timedelta

import pytest

from src.crm.models import Customer
from src.marketplace.models import Order, OrderStatus, PaymentMethod
from src.products.models import Product, ProductCategory, ProductStatus


@pytest.fixture
async def active_product(session):
    p = Product(
        slug="growth-test-product",
        name="Growth Test Product",
        description="desc",
        short_description="short",
        category=ProductCategory.PROMPT,
        status=ProductStatus.ACTIVE,
        price_usd=10.0,
        view_count=100,
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


@pytest.fixture
async def paid_customer(session):
    c = Customer(email="growth_buyer@example.com", name="Buyer", total_orders=1, total_spent_usd=11.0)
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


@pytest.fixture
async def paid_order(session, active_product, paid_customer):
    o = Order(
        order_number="ORD-GROWTH-001",
        customer_id=paid_customer.id,
        product_id=active_product.id,
        subtotal_usd=10.0,
        tax_usd=1.0,
        total_usd=11.0,
        platform_fee_usd=1.1,
        seller_revenue_usd=9.9,
        status=OrderStatus.PAID,
        payment_method=PaymentMethod.STRIPE,
        paid_at=datetime.utcnow(),
    )
    session.add(o)
    await session.commit()
    await session.refresh(o)
    return o


# --- 成長ダッシュボード ---

async def test_growth_dashboard_empty(client):
    """データなしでもダッシュボードが応答する"""
    resp = await client.get("/growth/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "today" in data
    assert "targets" in data
    assert data["targets"]["day1_orders"] == 100
    assert data["targets"]["daily_growth_pct"] == 105.0


async def test_growth_dashboard_with_order(client, paid_order):
    """注文があると当日KPIに反映される"""
    resp = await client.get("/growth/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["today"]["orders_count"] >= 1
    assert data["today"]["revenue_usd"] > 0
    assert data["today"]["day1_achievement_pct"] > 0


async def test_snapshot_record(client, paid_order):
    """スナップショット記録が正常動作する"""
    resp = await client.post("/growth/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "recorded"
    assert "snapshot_id" in data


async def test_snapshot_idempotent(client):
    """スナップショットを2回呼んでも重複しない（upsert）"""
    resp1 = await client.post("/growth/snapshot")
    resp2 = await client.post("/growth/snapshot")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["snapshot_id"] == resp2.json()["snapshot_id"]


async def test_ltv_report(client, paid_customer):
    """LTVレポートが応答する"""
    resp = await client.get("/growth/ltv")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_avg_ltv_usd" in data
    assert "improvement_advice" in data
    assert len(data["improvement_advice"]) > 0


async def test_funnel_report(client, active_product, paid_order):
    """ファネルレポートが応答する"""
    resp = await client.get("/growth/funnel?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert "funnel" in data
    assert "rates" in data
    assert data["funnel"]["orders_paid"] >= 1
    assert data["funnel"]["product_views"] >= 100


# --- 商材一括登録 ---

async def test_bulk_create_products(client):
    """10件の商材を一括登録できる"""
    items = [
        {
            "name": f"Bulk Product {i}",
            "description": f"説明{i}",
            "short_description": f"短い説明{i}",
            "category": "prompt",
            "price_usd": 10.0,
        }
        for i in range(10)
    ]
    resp = await client.post("/products/bulk", json=items)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 10
    slugs = [p["slug"] for p in data]
    assert len(set(slugs)) == 10  # スラッグ重複なし


async def test_bulk_create_deduplicates_slugs(client):
    """同名商材を複数登録してもスラッグが重複しない"""
    items = [
        {
            "name": "Duplicate Name",
            "description": "desc",
            "short_description": "short",
            "category": "prompt",
            "price_usd": 10.0,
        }
        for _ in range(3)
    ]
    resp = await client.post("/products/bulk", json=items)
    assert resp.status_code == 200
    slugs = [p["slug"] for p in resp.json()]
    assert len(set(slugs)) == 3


async def test_bulk_create_limit_exceeded(client):
    """31件はエラーになる"""
    items = [
        {"name": f"P{i}", "description": "d", "short_description": "s", "category": "prompt"}
        for i in range(31)
    ]
    resp = await client.post("/products/bulk", json=items)
    assert resp.status_code == 400


# --- レコメンド ---

async def test_recommendations(client, session, active_product):
    """同カテゴリの推薦商材が返る"""
    # 同カテゴリの商材を追加
    similar = Product(
        slug="similar-product",
        name="Similar Prompt",
        description="similar desc",
        short_description="short",
        category=ProductCategory.PROMPT,
        status=ProductStatus.ACTIVE,
        price_usd=10.0,
        sales_count=5,
    )
    session.add(similar)
    await session.commit()

    resp = await client.get(f"/products/{active_product.slug}/recommendations")
    assert resp.status_code == 200
    recs = resp.json()
    assert len(recs) >= 1
    assert all(r["slug"] != active_product.slug for r in recs)


async def test_recommendations_not_found(client):
    resp = await client.get("/products/nonexistent-slug/recommendations")
    assert resp.status_code == 404
