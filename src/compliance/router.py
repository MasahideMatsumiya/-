"""取引法コンプライアンスAPI"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.compliance.models import CustomerConsent, LegalDocument, RefundRequest
from src.config import settings
from src.database import get_session

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.get("/tokushoho")
async def tokushoho():
    """特定商取引法に基づく表記"""
    return {
        "title": "特定商取引法に基づく表記",
        "seller": "AI Marketplace 運営者",
        "product_type": "デジタルコンテンツ（プロンプト・AIツール・データセット等）",
        "price": (
            f"各商品ページに記載"
            f"（税込 {int(settings.default_price_usd * (1 + settings.tax_rate_jp))} USD前後）"
        ),
        "additional_fees": "なし",
        "payment_methods": ["クレジットカード（Stripe経由）"],
        "payment_timing": "注文確定時に即時決済",
        "delivery_method": "購入後即時ダウンロード（デジタルコンテンツ）",
        "delivery_timing": "決済完了後すぐ（ダウンロードURLをメールで送付）",
        "return_policy": (
            "デジタルコンテンツの性質上、原則として返品・返金不可。"
            "ただし商品の重大な瑕疵がある場合は購入から7日以内にお問い合わせください。"
        ),
        "cancellation": "デジタルコンテンツのため、ダウンロード開始後はキャンセル不可",
        "contact": "support@ai-marketplace.com",
    }


@router.get("/privacy-policy", response_model=dict)
async def privacy_policy(session: AsyncSession = Depends(get_session)):
    """現行プライバシーポリシー"""
    result = await session.execute(
        select(LegalDocument).where(
            LegalDocument.doc_type == "privacy", LegalDocument.is_current
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"message": "Privacy policy not found"}
    return {"version": doc.version, "content": doc.content, "effective_date": doc.effective_date}


@router.post("/consent")
async def record_consent(
    customer_id: int,
    doc_type: str,
    doc_version: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """同意記録（GDPR Article 7 対応）"""
    consent = CustomerConsent(
        customer_id=customer_id,
        doc_type=doc_type,
        doc_version=doc_version,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(consent)
    await session.commit()
    return {"status": "consent_recorded", "timestamp": consent.agreed_at}


@router.post("/refund-request")
async def request_refund(
    order_id: int,
    customer_id: int,
    reason: str,
    session: AsyncSession = Depends(get_session),
):
    """返金申請"""
    from src.marketplace.models import Order
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.customer_id != customer_id:
        raise HTTPException(403, "Not your order")

    # 購入から7日以内のみ受付
    if order.paid_at:
        days_since = (datetime.utcnow() - order.paid_at).days
        if days_since > 7:
            raise HTTPException(400, "Refund window (7 days) has passed")

    refund = RefundRequest(
        order_id=order_id,
        customer_id=customer_id,
        reason=reason,
        refund_amount_usd=order.total_usd,
    )
    session.add(refund)
    await session.commit()
    return {"status": "refund_requested", "refund_id": refund.id}


@router.patch("/refund-request/{refund_id}/process")
async def process_refund(
    refund_id: int,
    approve: bool,
    session: AsyncSession = Depends(get_session),
):
    """返金承認・Stripe返金実行"""
    refund = await session.get(RefundRequest, refund_id)
    if not refund:
        raise HTTPException(404, "Refund not found")

    from src.marketplace.models import Order, OrderStatus
    order = await session.get(Order, refund.order_id)

    if approve:
        if settings.stripe_secret_key and order.stripe_charge_id:
            import stripe
            stripe.api_key = settings.stripe_secret_key
            stripe_refund = stripe.Refund.create(
                charge=order.stripe_charge_id,
                amount=int(refund.refund_amount_usd * 100),
            )
            refund.stripe_refund_id = stripe_refund.id
        refund.status = "approved"
        order.status = OrderStatus.REFUNDED
        session.add(order)
    else:
        refund.status = "rejected"

    refund.processed_at = datetime.utcnow()
    session.add(refund)
    await session.commit()
    return {"status": refund.status}
