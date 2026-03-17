"""DL済み返金不正対策 テスト"""
from datetime import datetime, timedelta

import pytest

from src.compliance.models import RefundRequest
from src.crm.models import Customer
from src.marketplace.models import Order, OrderStatus, PaymentMethod
from src.products.models import Product, ProductCategory, ProductStatus


@pytest.fixture
async def product(session):
    p = Product(
        slug="test-prompt",
        name="Test Prompt",
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
async def customer(session):
    c = Customer(email="buyer@example.com", name="Buyer")
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


def _make_order(customer_id, product_id, download_count=0, paid_days_ago=1):
    return Order(
        order_number=f"ORD-TEST-{download_count}-{paid_days_ago}",
        customer_id=customer_id,
        product_id=product_id,
        subtotal_usd=10.0,
        tax_usd=1.0,
        total_usd=11.0,
        platform_fee_usd=1.0,
        seller_revenue_usd=9.0,
        status=OrderStatus.PAID,
        payment_method=PaymentMethod.STRIPE,
        download_count=download_count,
        max_downloads=5,
        paid_at=datetime.utcnow() - timedelta(days=paid_days_ago),
    )


async def test_refund_blocked_after_download(client, session, product, customer):
    """DL済みは返金申請を自動却下する"""
    order = _make_order(customer.id, product.id, download_count=1)
    session.add(order)
    await session.commit()
    await session.refresh(order)

    resp = await client.post(
        "/compliance/refund-request",
        params={"order_id": order.id, "customer_id": customer.id, "reason": "不要になった"},
    )
    assert resp.status_code == 400
    assert "ダウンロード済み" in resp.json()["detail"]


async def test_refund_allowed_before_download(client, session, product, customer):
    """未DLなら返金申請を受け付ける"""
    order = _make_order(customer.id, product.id, download_count=0)
    session.add(order)
    await session.commit()
    await session.refresh(order)

    resp = await client.post(
        "/compliance/refund-request",
        params={"order_id": order.id, "customer_id": customer.id, "reason": "商品が期待と違う"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "refund_requested"
    assert data["risk_score"] == 0


async def test_refund_token_revoked_on_approval(client, session, product, customer):
    """返金承認時にDLトークンが無効化される"""
    order = _make_order(customer.id, product.id, download_count=0)
    order.download_token = "valid-token-abc"
    order.download_expires_at = datetime.utcnow() + timedelta(days=30)
    session.add(order)
    await session.commit()
    await session.refresh(order)

    # 返金申請
    resp = await client.post(
        "/compliance/refund-request",
        params={"order_id": order.id, "customer_id": customer.id, "reason": "瑕疵あり"},
    )
    assert resp.status_code == 200
    refund_id = resp.json()["refund_id"]

    # 承認
    resp = await client.patch(
        f"/compliance/refund-request/{refund_id}/process", params={"approve": True}
    )
    assert resp.status_code == 200
    assert resp.json()["download_token_revoked"] is True

    # トークンが無効化されているか確認
    await session.refresh(order)
    assert order.download_token is None
    assert order.max_downloads == 0


async def test_repeat_refunder_flagged(client, session, product, customer):
    """2回以上返金承認された顧客は不正フラグが立つ"""
    for i in range(2):
        order = _make_order(customer.id, product.id, download_count=0)
        order.order_number = f"ORD-REPEAT-{i}"
        session.add(order)
        await session.commit()
        await session.refresh(order)

        resp = await client.post(
            "/compliance/refund-request",
            params={"order_id": order.id, "customer_id": customer.id, "reason": "test"},
        )
        assert resp.status_code == 200
        refund_id = resp.json()["refund_id"]

        await client.patch(
            f"/compliance/refund-request/{refund_id}/process", params={"approve": True}
        )

    # 3回目の申請はブロックされる
    order3 = _make_order(customer.id, product.id, download_count=0)
    order3.order_number = "ORD-REPEAT-3"
    session.add(order3)
    await session.commit()
    await session.refresh(order3)

    resp = await client.post(
        "/compliance/refund-request",
        params={"order_id": order3.id, "customer_id": customer.id, "reason": "test"},
    )
    assert resp.status_code == 403
    assert "restricted" in resp.json()["detail"]


async def test_refund_window_expired(client, session, product, customer):
    """7日を超えた返金申請は拒否される"""
    order = _make_order(customer.id, product.id, download_count=0, paid_days_ago=8)
    session.add(order)
    await session.commit()
    await session.refresh(order)

    resp = await client.post(
        "/compliance/refund-request",
        params={"order_id": order.id, "customer_id": customer.id, "reason": "test"},
    )
    assert resp.status_code == 400
    assert "7 days" in resp.json()["detail"]


async def test_risk_assessment_endpoint(client, session, customer):
    """顧客リスク評価エンドポイント"""
    resp = await client.get(f"/compliance/refund-risk/{customer.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["risk_level"] == "low"
    assert data["fraud_flagged"] is False
