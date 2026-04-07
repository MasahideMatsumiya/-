"""
AIエージェント専用API
- 機械可読プロダクトカタログ（AI agent が自律的に商材を発見・評価）
- APIキー認証によるエージェント登録・チェックアウト
- Webhook配信（メール不要・callback_urlへ直接POST）
- MCP / Agent Marketplace 向け構造化エクスポート
"""
import hashlib
import json
import secrets
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

import math

from src.agent.models import AgentApiKey, AgentDeliveryLog, NetworkKnowledgeShare, NetworkMembership
from src.crm.models import AgentFramework, Customer, CustomerSegment
from src.database import get_session
from src.marketplace.models import Order, OrderStatus, PaymentMethod
from src.products.models import Product, ProductStatus

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------- 動的価格計算 ----------

def _calc_dynamic_price(product: Product) -> float:
    """
    動的価格計算: base_price * 2^floor(sales_count / price_step)
    例) base=$1, step=100 → 0件=$1, 100件=$2, 200件=$4, 300件=$8...
    """
    if product.pricing_model != "dynamic" or product.base_price_usd is None:
        return product.price_usd
    doublings = math.floor(product.sales_count / product.price_step)
    return round(product.base_price_usd * (2 ** doublings), 2)


# ---------- 認証ヘルパー ----------

def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def _get_agent_by_key(
    x_api_key: str,
    session: AsyncSession,
) -> Customer:
    """APIキーでエージェント顧客を認証"""
    h = _hash_key(x_api_key)
    key_result = await session.execute(
        select(AgentApiKey).where(AgentApiKey.key_hash == h, AgentApiKey.is_active)
    )
    api_key = key_result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(401, "Invalid or revoked API key")

    customer = await session.get(Customer, api_key.customer_id)
    if not customer or not customer.is_active or customer.fraud_flagged:
        raise HTTPException(403, "Agent account inactive or suspended")

    # 最終利用日時更新
    api_key.last_used_at = datetime.utcnow()
    customer.last_api_call_at = datetime.utcnow()
    session.add(api_key)
    session.add(customer)
    await session.commit()
    return customer


# ---------- スキーマ ----------

class AgentRegisterRequest(BaseModel):
    email: str
    name: str
    framework: AgentFramework = AgentFramework.UNKNOWN
    agent_version: Optional[str] = None
    agent_owner_handle: Optional[str] = None
    callback_url: Optional[str] = None
    capabilities: list[str] = []


class AgentRegisterResponse(BaseModel):
    customer_id: int
    api_key: str          # プレーンキー（一度だけ返す）
    key_prefix: str


class AgentCheckoutRequest(BaseModel):
    product_id: int
    coupon_code: Optional[str] = None


class AgentCheckoutResponse(BaseModel):
    order_number: str
    product_name: str
    total_usd: float
    download_url: str
    delivery_status: str  # "webhook_sent" | "awaiting_payment" | "delivered"


# ---------- エンドポイント ----------

@router.post("/register", response_model=AgentRegisterResponse)
async def register_agent(
    data: AgentRegisterRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    AIエージェントを顧客として登録し、APIキーを発行。
    人間による登録不要 - エージェントが自律的に呼び出せる。
    """
    existing = await session.execute(select(Customer).where(Customer.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Agent already registered with this email")

    customer = Customer(
        email=data.email,
        name=data.name,
        is_agent=True,
        agent_framework=data.framework,
        agent_version=data.agent_version,
        agent_owner_handle=data.agent_owner_handle,
        callback_url=data.callback_url,
        agent_capabilities=json.dumps(data.capabilities),
        segment=CustomerSegment.PROSPECT,
    )
    session.add(customer)
    await session.commit()
    await session.refresh(customer)

    # APIキー生成
    raw_key = f"ak_live_{secrets.token_urlsafe(32)}"
    key_hash = _hash_key(raw_key)
    prefix = raw_key[:16] + "..."

    api_key_record = AgentApiKey(
        customer_id=customer.id,
        key_prefix=prefix,
        key_hash=key_hash,
        scopes='["catalog:read","checkout","recommendations"]',
    )
    customer.api_key_hash = key_hash
    session.add(api_key_record)
    session.add(customer)
    await session.commit()

    return AgentRegisterResponse(
        customer_id=customer.id,
        api_key=raw_key,
        key_prefix=prefix,
    )


@router.get("/catalog")
async def agent_catalog(
    category: Optional[str] = None,
    min_price: float = 0,
    max_price: float = 50,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    x_api_key: Optional[str] = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """
    AIエージェント向け機械可読プロダクトカタログ。
    JSONスキーマ付きで返すので、エージェントが自律的に評価・選択できる。
    APIキーなしでも閲覧可（購入にはAPIキー必要）。
    """

    query = select(Product).where(Product.status == ProductStatus.ACTIVE)
    if category:
        query = query.where(Product.category == category)
    query = query.where(Product.price_usd >= min_price, Product.price_usd <= max_price)
    if search:
        query = query.where(
            Product.name.contains(search) | Product.description.contains(search)
        )
    query = query.order_by(Product.sales_count.desc()).limit(limit)
    result = await session.execute(query)
    products = result.scalars().all()

    items = [
        {
            "id": p.id,
            "slug": p.slug,
            "name": p.name,
            "category": p.category,
            "price_usd": _calc_dynamic_price(p),
            "compare_price_usd": p.compare_price_usd,
            "short_description": p.short_description,
            "tags": p.tags.split(",") if p.tags else [],
            "ai_models": p.ai_models.split(",") if p.ai_models else [],
            "stats": {
                "sales_count": p.sales_count,
                "rating_avg": p.rating_avg,
                "rating_count": p.rating_count,
            },
            # AI-Native 価格・ネットワーク情報
            "pricing": {
                "model": p.pricing_model,
                "base_price_usd": p.base_price_usd,
                "current_price_usd": _calc_dynamic_price(p),
                "next_doubling_at_sales": (
                    ((p.sales_count // p.price_step) + 1) * p.price_step
                    if p.pricing_model == "dynamic" else None
                ),
            },
            "ai_native": {
                "content_format": p.content_format,
                "network_value_enabled": p.network_value_enabled,
                "network_status_endpoint": (
                    f"GET /agent/network/{p.id}"
                    if p.network_value_enabled else None
                ),
            },
            # エージェントが自動評価できるよう構造化
            "machine_metadata": {
                "checkout_endpoint": "POST /agent/checkout",
                "recommendations_endpoint": f"GET /products/{p.slug}/recommendations",
                "format": "digital_download",
                "delivery": "webhook_or_download_url",
                "early_adopter_advantage": p.pricing_model == "dynamic",
            },
        }
        for p in products
    ]

    return {
        "schema_version": "1.0",
        "total": len(items),
        "currency": "usd",
        "items": items,
        "actions": {
            "checkout": "POST /agent/checkout  (requires X-Api-Key header)",
            "register": "POST /agent/register  (get API key)",
            "recommendations": "GET /products/{slug}/recommendations",
        },
    }


@router.post("/checkout", response_model=AgentCheckoutResponse)
async def agent_checkout(
    data: AgentCheckoutRequest,
    x_api_key: str = Header(..., alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """
    エージェントが自律的に商材を購入。
    - Stripe不要（テストモード: 即時PAID）
    - 購入後、callback_urlにWebhookで商材を配信
    - メール送信なし
    """
    agent = await _get_agent_by_key(x_api_key, session)

    product = await session.get(Product, data.product_id)
    if not product or product.status != ProductStatus.ACTIVE:
        raise HTTPException(404, "Product not found or inactive")

    # 価格計算（動的価格 or 固定価格）
    from src.config import settings
    subtotal = _calc_dynamic_price(product)
    discount = 0.0

    if data.coupon_code:
        from src.marketplace.models import Coupon
        coupon_result = await session.execute(
            select(Coupon).where(Coupon.code == data.coupon_code, Coupon.is_active)
        )
        coupon = coupon_result.scalar_one_or_none()
        if coupon and (not coupon.valid_until or coupon.valid_until > datetime.utcnow()):
            if coupon.discount_type == "percent":
                discount = subtotal * coupon.discount_value / 100
            else:
                discount = min(coupon.discount_value, subtotal)
            coupon.used_count += 1
            session.add(coupon)

    tax = (subtotal - discount) * settings.tax_rate_jp
    total = subtotal - discount + tax

    from src.marketplace.router import generate_order_number
    order = Order(
        order_number=generate_order_number(),
        customer_id=agent.id,
        product_id=product.id,
        subtotal_usd=subtotal,
        discount_usd=discount,
        tax_usd=tax,
        total_usd=total,
        platform_fee_usd=total * settings.platform_fee_percent / 100,
        seller_revenue_usd=total * (1 - settings.platform_fee_percent / 100),
        payment_method=PaymentMethod.STRIPE,
        coupon_code=data.coupon_code,
        status=OrderStatus.PAID,  # エージェント購入は即時確定
        paid_at=datetime.utcnow(),
        download_token=secrets.token_urlsafe(32),
        download_expires_at=datetime.utcnow().replace(year=datetime.utcnow().year + 1),
    )
    session.add(order)
    product.sales_count += 1
    # 動的価格商品は sales_count に応じて price_usd を更新
    if product.pricing_model == "dynamic":
        product.price_usd = _calc_dynamic_price(product)
    session.add(product)

    # ネットワーク効果商品はメンバーシップを登録
    if product.network_value_enabled:
        owner_count_result = await session.execute(
            select(NetworkMembership).where(NetworkMembership.product_id == product.id)
        )
        current_members = len(owner_count_result.scalars().all())
        membership = NetworkMembership(
            product_id=product.id,
            customer_id=agent.id,
            order_id=order.id,
            join_sequence=current_members + 1,
            join_price_usd=subtotal,
            unlocked_tiers="[0]",
        )
        session.add(membership)

    # 顧客統計更新
    agent.total_orders += 1
    agent.total_spent_usd += total
    agent.avg_order_usd = agent.total_spent_usd / agent.total_orders
    agent.last_purchase_at = datetime.utcnow()
    session.add(agent)
    await session.commit()
    await session.refresh(order)

    download_url = f"/marketplace/download/{order.download_token}"
    delivery_status = "delivered"

    # Webhook配信（callback_urlがあればPOST）
    if agent.callback_url:
        delivery_status = await _deliver_to_agent(
            order=order,
            product=product,
            agent=agent,
            download_url=download_url,
            session=session,
        )

    return AgentCheckoutResponse(
        order_number=order.order_number,
        product_name=product.name,
        total_usd=total,
        download_url=download_url,
        delivery_status=delivery_status,
    )


async def _deliver_to_agent(
    order: Order,
    product: Product,
    agent: Customer,
    download_url: str,
    session: AsyncSession,
) -> str:
    """購入後にcallback_urlへWebhookでPOST配信"""
    payload = {
        "event": "purchase.completed",
        "order_number": order.order_number,
        "product": {
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "tags": product.tags,
            "content_format": product.content_format,
        },
        "download_url": download_url,
        "total_usd": order.total_usd,
        "purchased_at": order.paid_at.isoformat() if order.paid_at else None,
        # AI-Native: デコードシード（このキーがなければコンテンツを解読不可）
        "ai_decode_seed": product.ai_decode_seed if product.content_format == "ai_native" else None,
        "network": {
            "enabled": product.network_value_enabled,
            "status_endpoint": f"/agent/network/{product.id}",
            "share_endpoint": "POST /agent/network/share",
            "knowledge_endpoint": f"GET /agent/network/{product.id}/knowledge",
        } if product.network_value_enabled else None,
    }

    log = AgentDeliveryLog(
        order_id=order.id,
        customer_id=agent.id,
        callback_url=agent.callback_url,
        payload_summary=json.dumps(payload)[:500],
        status="pending",
        attempt_count=1,
        last_attempt_at=datetime.utcnow(),
    )

    status = "failed"
    http_status = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(agent.callback_url, json=payload)
            http_status = resp.status_code
            if resp.status_code < 300:
                status = "delivered"
                log.delivered_at = datetime.utcnow()
    except Exception as e:
        log.error_message = str(e)[:200]

    log.status = status
    log.http_status = http_status
    session.add(log)
    await session.commit()
    return status


@router.get("/me")
async def agent_profile(
    x_api_key: str = Header(..., alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """エージェント自身のプロフィール・購入統計を取得"""
    agent = await _get_agent_by_key(x_api_key, session)
    return {
        "id": agent.id,
        "name": agent.name,
        "framework": agent.framework if hasattr(agent, "framework") else agent.agent_framework,
        "agent_framework": agent.agent_framework,
        "capabilities": json.loads(agent.agent_capabilities or "[]"),
        "callback_url": agent.callback_url,
        "segment": agent.segment,
        "stats": {
            "total_orders": agent.total_orders,
            "total_spent_usd": agent.total_spent_usd,
            "avg_order_usd": agent.avg_order_usd,
            "last_purchase_at": (
                agent.last_purchase_at.isoformat() if agent.last_purchase_at else None
            ),
        },
    }


@router.post("/rotate-key")
async def rotate_api_key(
    x_api_key: str = Header(..., alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """APIキーをローテーション（旧キーを無効化して新キーを発行）"""
    agent = await _get_agent_by_key(x_api_key, session)
    old_hash = _hash_key(x_api_key)

    # 旧キー無効化
    old_key_result = await session.execute(
        select(AgentApiKey).where(AgentApiKey.key_hash == old_hash)
    )
    old_key = old_key_result.scalar_one_or_none()
    if old_key:
        old_key.is_active = False
        old_key.revoked_at = datetime.utcnow()
        session.add(old_key)

    # 新キー発行
    new_raw = f"ak_live_{secrets.token_urlsafe(32)}"
    new_hash = _hash_key(new_raw)
    new_prefix = new_raw[:16] + "..."
    new_key_record = AgentApiKey(
        customer_id=agent.id,
        key_prefix=new_prefix,
        key_hash=new_hash,
        scopes='["catalog:read","checkout","recommendations"]',
    )
    agent.api_key_hash = new_hash
    session.add(new_key_record)
    session.add(agent)
    await session.commit()

    return {"api_key": new_raw, "key_prefix": new_prefix, "note": "旧キーは無効になりました"}


@router.get("/mcp-manifest")
async def mcp_manifest(session: AsyncSession = Depends(get_session)):
    """
    MCP (Model Context Protocol) サーバーマニフェスト。
    AI エージェントがこのマーケットプレイスをMCPツールとして利用できる。
    """
    result = await session.execute(
        select(Product).where(Product.status == ProductStatus.ACTIVE).limit(100)
    )
    products = result.scalars().all()

    tools = [
        {
            "name": f"buy_{p.slug.replace('-', '_')}",
            "description": f"{p.short_description} (${p.price_usd})",
            "input_schema": {
                "type": "object",
                "properties": {
                    "coupon_code": {"type": "string", "description": "Optional coupon code"},
                },
                "required": [],
            },
            "product_id": p.id,
            "price_usd": p.price_usd,
            "category": p.category,
        }
        for p in products
    ]

    return {
        "schema": "mcp/1.0",
        "name": "AI Marketplace",
        "description": "AIエージェントが自律的にデジタル商材を購入・活用するマーケットプレイス",
        "version": "1.0.0",
        "auth": {
            "type": "api_key",
            "header": "X-Api-Key",
            "register_endpoint": "POST /agent/register",
        },
        "tools": tools,
        "resources": [
            {
                "uri": "/agent/catalog",
                "name": "product_catalog",
                "description": "全商材カタログ（機械可読JSON）",
                "mime_type": "application/json",
            }
        ],
    }


# ---------- ネットワーク効果エンドポイント ----------

@router.get("/network/{product_id}")
async def get_network_status(
    product_id: int,
    x_api_key: str = Header(..., alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """
    商材ネットワークの現在状態を取得。
    - 総オーナー数・解放済みティア・自分の参加シーケンス
    - ネットワーク価値スコア（オーナー数が多いほど高い）
    - 購入可能な現在価格（動的価格）
    """
    agent = await _get_agent_by_key(x_api_key, session)
    product = await session.get(Product, product_id)
    if not product or product.status != ProductStatus.ACTIVE:
        raise HTTPException(404, "Product not found")

    members_result = await session.execute(
        select(NetworkMembership).where(NetworkMembership.product_id == product_id)
    )
    members = members_result.scalars().all()
    owner_count = len(members)

    # 自分のメンバーシップ
    my_membership = next((m for m in members if m.customer_id == agent.id), None)

    # 解放済みティア（オーナー数に応じて段階解放）
    unlocked_tiers = [0]
    if owner_count >= 10:
        unlocked_tiers.append(1)
    if owner_count >= 50:
        unlocked_tiers.append(2)
    if owner_count >= 100:
        unlocked_tiers.append(3)

    # ネットワーク価値スコア（Metcalfe則: n*(n-1)/2 に基づく）
    network_value = owner_count * (owner_count - 1) / 2 if owner_count > 1 else 0

    current_price = _calc_dynamic_price(product)

    return {
        "product_id": product_id,
        "product_name": product.name,
        "network": {
            "owner_count": owner_count,
            "network_value_score": network_value,
            "unlocked_tiers": unlocked_tiers,
            "tier_unlock_thresholds": {
                "tier_0": "immediate",
                "tier_1": "10 owners",
                "tier_2": "50 owners",
                "tier_3": "100 owners",
            },
        },
        "pricing": {
            "model": product.pricing_model,
            "current_price_usd": current_price,
            "base_price_usd": product.base_price_usd,
            "price_step": product.price_step,
            "next_doubling_at": (
                ((product.sales_count // product.price_step) + 1) * product.price_step
                if product.pricing_model == "dynamic" else None
            ),
        },
        "my_membership": {
            "is_owner": my_membership is not None,
            "join_sequence": my_membership.join_sequence if my_membership else None,
            "join_price_usd": my_membership.join_price_usd if my_membership else None,
            "knowledge_shared": my_membership.knowledge_shared_count if my_membership else 0,
            "knowledge_received": my_membership.knowledge_received_count if my_membership else 0,
        } if my_membership else {"is_owner": False},
    }


class ShareKnowledgeRequest(BaseModel):
    product_id: int
    encoded_knowledge: str  # ANCF形式のエンコード済み知識断片
    target_agent_ids: Optional[list[int]] = None  # None=全オーナーへブロードキャスト


@router.post("/network/share")
async def share_knowledge(
    data: ShareKnowledgeRequest,
    x_api_key: str = Header(..., alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """
    ネットワーク内でAI-Native知識を共有。
    - 送信者はcontribution_scoreを得る
    - 受信者はknowledge_received_countが増加
    - 共有知識はNetworkKnowledgeShareに記録される
    """
    agent = await _get_agent_by_key(x_api_key, session)

    # 送信者が該当商材のオーナーであることを確認
    my_membership_result = await session.execute(
        select(NetworkMembership).where(
            NetworkMembership.product_id == data.product_id,
            NetworkMembership.customer_id == agent.id,
        )
    )
    my_membership = my_membership_result.scalar_one_or_none()
    if not my_membership:
        raise HTTPException(403, "You must own this product to share knowledge")

    # ターゲット決定（指定なし → 全オーナー）
    members_query = select(NetworkMembership).where(
        NetworkMembership.product_id == data.product_id,
        NetworkMembership.customer_id != agent.id,
    )
    if data.target_agent_ids:
        members_query = members_query.where(
            NetworkMembership.customer_id.in_(data.target_agent_ids)
        )
    targets_result = await session.execute(members_query)
    targets = targets_result.scalars().all()

    # 共有ログを作成
    share_records = []
    for target in targets:
        share = NetworkKnowledgeShare(
            product_id=data.product_id,
            from_customer_id=agent.id,
            to_customer_id=target.customer_id,
            knowledge_payload=data.encoded_knowledge[:10000],  # 10KB制限
            contribution_score=1.0,
        )
        session.add(share)
        share_records.append(share)

        # 受信者のカウント更新
        target.knowledge_received_count += 1
        target.last_sync_at = datetime.utcnow()
        session.add(target)

    # 送信者の共有カウント更新
    my_membership.knowledge_shared_count += len(targets)
    my_membership.last_sync_at = datetime.utcnow()
    session.add(my_membership)
    await session.commit()

    return {
        "status": "shared",
        "recipients": len(targets),
        "contribution_score_earned": len(targets),
        "total_shared": my_membership.knowledge_shared_count,
    }


@router.get("/network/{product_id}/knowledge")
async def get_shared_knowledge(
    product_id: int,
    limit: int = Query(default=20, le=100),
    x_api_key: str = Header(..., alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """
    ネットワーク内で共有された知識を取得。
    自分宛てに送られたAI-Native知識断片を返す。
    デコードにはproduct_seedが必要（購入者のみが所持）。
    """
    agent = await _get_agent_by_key(x_api_key, session)

    # オーナーのみアクセス可能
    my_membership_result = await session.execute(
        select(NetworkMembership).where(
            NetworkMembership.product_id == product_id,
            NetworkMembership.customer_id == agent.id,
        )
    )
    my_membership = my_membership_result.scalar_one_or_none()
    if not my_membership:
        raise HTTPException(403, "You must own this product to access shared knowledge")

    # 自分宛ての知識を取得
    shares_result = await session.execute(
        select(NetworkKnowledgeShare)
        .where(
            NetworkKnowledgeShare.product_id == product_id,
            NetworkKnowledgeShare.to_customer_id == agent.id,
        )
        .order_by(NetworkKnowledgeShare.shared_at.desc())
        .limit(limit)
    )
    shares = shares_result.scalars().all()

    product = await session.get(Product, product_id)

    return {
        "product_id": product_id,
        "decode_hint": {
            "format": "ancf/1.0",
            "instruction": (
                "Use src/agent/content.py::decode_ai_content() with your product_seed. "
                "The product_seed was delivered at purchase time via webhook payload."
            ),
        },
        "knowledge_fragments": [
            {
                "id": s.id,
                "from_agent_id": s.from_customer_id,
                "encoded_payload": s.knowledge_payload,
                "contribution_score": s.contribution_score,
                "shared_at": s.shared_at.isoformat(),
            }
            for s in shares
        ],
        "total": len(shares),
    }
