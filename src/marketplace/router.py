"""取引所API - 注文・決済・ダウンロード"""
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

logger = logging.getLogger(__name__)

from src.config import settings
from src.database import get_session
from src.marketplace.models import Coupon, DownloadLog, Order, OrderStatus, PaymentMethod
from src.marketplace.schemas import CheckoutRequest, CheckoutResponse, OrderPublic
from src.products.models import Product

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


def generate_order_number() -> str:
    from datetime import date
    today = date.today().strftime("%Y%m%d")
    rand = secrets.token_hex(3).upper()
    return f"ORD-{today}-{rand}"


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    data: CheckoutRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Stripe決済セッション作成"""
    product = await session.get(Product, data.product_id)
    if not product:
        raise HTTPException(404, "Product not found")

    subtotal = product.price_usd
    discount = 0.0

    # クーポン適用
    if data.coupon_code:
        result = await session.execute(
            select(Coupon).where(Coupon.code == data.coupon_code, Coupon.is_active)
        )
        coupon = result.scalar_one_or_none()
        if coupon and (not coupon.valid_until or coupon.valid_until > datetime.utcnow()):
            if coupon.discount_type == "percent":
                discount = subtotal * coupon.discount_value / 100
            else:
                discount = min(coupon.discount_value, subtotal)
            coupon.used_count += 1
            session.add(coupon)

    tax = (subtotal - discount) * settings.tax_rate_jp
    total = subtotal - discount + tax
    platform_fee = total * settings.platform_fee_percent / 100
    seller_revenue = total - platform_fee

    order = Order(
        order_number=generate_order_number(),
        customer_id=data.customer_id,
        product_id=data.product_id,
        subtotal_usd=subtotal,
        discount_usd=discount,
        tax_usd=tax,
        total_usd=total,
        platform_fee_usd=platform_fee,
        seller_revenue_usd=seller_revenue,
        payment_method=PaymentMethod.STRIPE,
        coupon_code=data.coupon_code,
        ip_address=request.client.host if request.client else None,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    # Stripe Payment Intent 作成
    stripe_client_secret = None
    if settings.stripe_secret_key:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        intent = stripe.PaymentIntent.create(
            amount=int(total * 100),  # cents
            currency=settings.currency,
            metadata={"order_id": order.id, "order_number": order.order_number},
        )
        order.stripe_payment_intent_id = intent.id
        session.add(order)
        await session.commit()
        stripe_client_secret = intent.client_secret

    return CheckoutResponse(
        order_id=order.id,
        order_number=order.order_number,
        total_usd=total,
        stripe_client_secret=stripe_client_secret,
    )


@router.post("/webhook")
@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    """Stripe Webhook - 決済確認"""
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    # 署名検証（webhook_secret設定済みの場合は必須）
    if settings.stripe_webhook_secret:
        try:
            event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
        except stripe.SignatureVerificationError:
            logger.warning("Stripe webhook signature verification failed")
            raise HTTPException(400, "Invalid signature")
        except Exception as e:
            logger.error(f"Stripe webhook error: {e}")
            raise HTTPException(400, "Webhook error")
    else:
        # 開発環境：署名なしで処理（本番では必ずwebhook_secretを設定すること）
        import json
        try:
            event = json.loads(payload)
            logger.warning("Stripe webhook received without signature verification (dev mode)")
        except Exception:
            raise HTTPException(400, "Invalid payload")

    event_type = event["type"] if isinstance(event, dict) else event.type
    logger.info(f"Stripe webhook received: {event_type}")

    if event_type == "payment_intent.succeeded":
        obj = event["data"]["object"] if isinstance(event, dict) else event.data.object
        pi_id = obj["id"] if isinstance(obj, dict) else obj.id
        logger.info(f"PaymentIntent succeeded: {pi_id}")
        result = await session.execute(
            select(Order).where(Order.stripe_payment_intent_id == pi_id)
        )
        order = result.scalar_one_or_none()
        if order and order.status != OrderStatus.PAID:
            await _fulfill_order(order, session)
            logger.info(f"Order fulfilled: {order.order_number}")
        elif order:
            logger.info(f"Order already fulfilled: {order.order_number}")
        else:
            logger.warning(f"No order found for PaymentIntent: {pi_id}")

    return {"status": "ok"}


async def _fulfill_order(order: Order, session: AsyncSession):
    """注文確定・商品配信・購入確認メール送信"""
    order.status = OrderStatus.PAID
    order.paid_at = datetime.utcnow()
    order.download_token = secrets.token_urlsafe(32)
    order.download_expires_at = datetime.utcnow() + timedelta(days=30)

    # 商品販売数更新
    product = await session.get(Product, order.product_id)
    if product:
        product.sales_count += 1
        session.add(product)

    session.add(order)
    await session.commit()

    # 購入確認メール（失敗してもオーダーは確定済みなので例外を飲む）
    if order.customer_id and product:
        try:
            from src.crm.email import send_purchase_email
            download_url = f"/marketplace/download/{order.download_token}"
            await send_purchase_email(
                customer_id=order.customer_id,
                product_name=product.name,
                download_url=download_url,
                order_number=order.order_number,
                session=session,
            )
        except Exception:
            pass  # メール送信失敗はサイレントに処理


@router.get("/download/{token}")
async def download_product(
    token: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """購入後ダウンロード"""
    result = await session.execute(select(Order).where(Order.download_token == token))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Invalid download token")
    if order.download_expires_at and order.download_expires_at < datetime.utcnow():
        raise HTTPException(410, "Download link expired")
    if order.download_count >= order.max_downloads:
        raise HTTPException(429, "Download limit reached")

    product = await session.get(Product, order.product_id)
    order.download_count += 1
    log = DownloadLog(order_id=order.id, ip_address=request.client.host if request.client else "")
    session.add(order)
    session.add(log)
    await session.commit()

    # ローカルファイルの場合は直接配信
    if product.download_url and not product.download_url.startswith("http"):
        content_path = Path(product.download_url)
        if not content_path.is_absolute():
            content_path = Path(__file__).parent.parent.parent / product.download_url
        if content_path.exists():
            return FileResponse(
                path=str(content_path),
                filename=content_path.name,
                media_type="application/json",
            )

    return {"download_url": product.download_url, "product_name": product.name}


@router.get("/config")
async def get_config():
    """フロントエンド用設定（Stripe publishable_key）"""
    if not settings.stripe_publishable_key:
        raise HTTPException(503, "Stripe not configured")
    return {"publishable_key": settings.stripe_publishable_key}


@router.get("/orders/by-id/{order_id}", response_model=OrderPublic)
async def get_order_by_id(order_id: int, session: AsyncSession = Depends(get_session)):
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    # Webhook が届く前でも、Stripe 側で決済済みなら即座に注文を確定する
    if order.status == OrderStatus.PENDING and order.stripe_payment_intent_id and settings.stripe_secret_key:
        try:
            import stripe
            stripe.api_key = settings.stripe_secret_key
            pi = stripe.PaymentIntent.retrieve(order.stripe_payment_intent_id)
            if pi.status == "succeeded":
                await _fulfill_order(order, session)
                await session.refresh(order)
                logger.info(f"Order fulfilled via polling: {order.order_number}")
        except Exception as e:
            logger.warning(f"Stripe polling check failed: {e}")

    return order


@router.get("/orders/{order_number}", response_model=OrderPublic)
async def get_order(order_number: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Order).where(Order.order_number == order_number))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.post("/orders/{order_id}/pay-test")
async def pay_test(order_id: int, session: AsyncSession = Depends(get_session)):
    """
    テスト用・手動決済完了エンドポイント。
    Stripe未設定時、またはTESTING環境変数が設定されている場合に有効。
    本番環境（stripe_secret_key設定済み・TESTING未設定）では403を返す。
    """
    import os
    if settings.stripe_secret_key and not os.getenv("TESTING"):
        raise HTTPException(403, "Stripe設定済みの環境ではこのエンドポイントは使用できません")
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status == OrderStatus.PAID:
        raise HTTPException(409, "Already paid")
    await _fulfill_order(order, session)
    return {
        "status": "paid",
        "order_number": order.order_number,
        "download_token": order.download_token,
        "download_url": f"/marketplace/download/{order.download_token}",
    }
