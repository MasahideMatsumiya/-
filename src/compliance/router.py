"""取引法コンプライアンスAPI"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

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
            "デジタルコンテンツの性質上、ダウンロード開始後は返品・返金不可。"
            "未ダウンロードかつ購入から7日以内の場合のみ、"
            "商品の重大な瑕疵を理由とした返金申請を受け付けます。"
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


def _calc_risk(order, customer, past_refunds: int) -> tuple[int, list[str]]:
    """リスクスコアとリスク理由を計算。score: 0=低, 1=中, 2=高"""
    score = 0
    reasons = []

    if order.download_count > 0:
        score += 2
        reasons.append(f"downloaded:{order.download_count}回")

    if past_refunds >= 1:
        score += 1
        reasons.append(f"past_refunds:{past_refunds}回")

    if past_refunds >= 2:
        score += 1
        reasons.append("repeat_refunder")

    if customer and customer.fraud_flagged:
        score += 2
        reasons.append("fraud_flagged_account")

    return min(score, 2), reasons


@router.post("/refund-request")
async def request_refund(
    order_id: int,
    customer_id: int,
    reason: str,
    session: AsyncSession = Depends(get_session),
):
    """返金申請。DL済みの場合は自動却下。"""
    from src.crm.models import Customer
    from src.marketplace.models import Order

    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.customer_id != customer_id:
        raise HTTPException(403, "Not your order")

    customer = await session.get(Customer, customer_id)

    # 不正フラグ済みアカウントはブロック
    if customer and customer.fraud_flagged:
        raise HTTPException(403, "Account is restricted. Contact support.")

    # 購入から7日以内のみ受付
    if order.paid_at:
        days_since = (datetime.utcnow() - order.paid_at).days
        if days_since > 7:
            raise HTTPException(400, "Refund window (7 days) has passed")

    # 過去の返金申請数（承認済み）
    past_refunds_result = await session.execute(
        select(func.count(RefundRequest.id)).where(
            RefundRequest.customer_id == customer_id,
            RefundRequest.status == "approved",
        )
    )
    past_refunds = past_refunds_result.scalar() or 0

    risk_score, risk_reasons = _calc_risk(order, customer, past_refunds)
    was_downloaded = order.download_count > 0

    # DL済みは自動却下（特定商取引法・利用規約に基づく）
    if was_downloaded:
        refund = RefundRequest(
            order_id=order_id,
            customer_id=customer_id,
            reason=reason,
            refund_amount_usd=order.total_usd,
            status="auto_rejected",
            was_downloaded=True,
            download_count_at_request=order.download_count,
            risk_score=risk_score,
            risk_reasons=",".join(risk_reasons),
            processed_at=datetime.utcnow(),
            notes="ダウンロード済みのため自動却下。利用規約第X条に基づく。",
        )
        session.add(refund)
        await session.commit()
        raise HTTPException(
            400,
            "返金不可: 商品をダウンロード済みです。"
            "デジタルコンテンツはダウンロード後の返金を承っておりません。"
            "商品に重大な瑕疵がある場合は support@ai-marketplace.com までご連絡ください。",
        )

    refund = RefundRequest(
        order_id=order_id,
        customer_id=customer_id,
        reason=reason,
        refund_amount_usd=order.total_usd,
        was_downloaded=False,
        download_count_at_request=order.download_count,
        risk_score=risk_score,
        risk_reasons=",".join(risk_reasons),
    )
    session.add(refund)
    await session.commit()
    await session.refresh(refund)

    return {
        "status": "refund_requested",
        "refund_id": refund.id,
        "risk_score": risk_score,
        # 高リスクは管理者に通知（実運用ではメール送信）
        "admin_review_required": risk_score >= 1,
    }


@router.patch("/refund-request/{refund_id}/process")
async def process_refund(
    refund_id: int,
    approve: bool,
    session: AsyncSession = Depends(get_session),
):
    """返金承認・Stripe返金実行。承認時はDLトークンを即時無効化。"""
    refund = await session.get(RefundRequest, refund_id)
    if not refund:
        raise HTTPException(404, "Refund not found")
    if refund.status not in ("pending",):
        raise HTTPException(400, f"Cannot process refund in status: {refund.status}")

    from src.crm.models import Customer
    from src.marketplace.models import Order, OrderStatus

    order = await session.get(Order, refund.order_id)
    customer = await session.get(Customer, refund.customer_id)

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

        # DLトークン即時無効化（返金後に使用できないようにする）
        order.download_token = None
        order.download_expires_at = datetime.utcnow()
        order.max_downloads = 0

        # 顧客の返金カウント更新・不正判定
        if customer:
            customer.refund_count = (customer.refund_count or 0) + 1
            if customer.refund_count >= 2:
                customer.fraud_flagged = True
                customer.fraud_flagged_at = datetime.utcnow()
                customer.fraud_reason = f"返金{customer.refund_count}回（自動フラグ）"
            session.add(customer)

        session.add(order)
    else:
        refund.status = "rejected"

    refund.processed_at = datetime.utcnow()
    session.add(refund)
    await session.commit()
    return {"status": refund.status, "download_token_revoked": approve}


@router.get("/refund-risk/{customer_id}")
async def customer_refund_risk(customer_id: int, session: AsyncSession = Depends(get_session)):
    """顧客の返金リスク評価"""
    from src.crm.models import Customer

    customer = await session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    refunds_result = await session.execute(
        select(func.count(RefundRequest.id), RefundRequest.status).where(
            RefundRequest.customer_id == customer_id
        ).group_by(RefundRequest.status)
    )
    refund_stats = {status: count for count, status in refunds_result.all()}

    return {
        "customer_id": customer_id,
        "fraud_flagged": customer.fraud_flagged,
        "fraud_reason": customer.fraud_reason,
        "refund_count_approved": refund_stats.get("approved", 0),
        "refund_count_auto_rejected": refund_stats.get("auto_rejected", 0),
        "refund_count_pending": refund_stats.get("pending", 0),
        "risk_level": (
            "blocked" if customer.fraud_flagged
            else "high" if (customer.refund_count or 0) >= 2
            else "medium" if (customer.refund_count or 0) >= 1
            else "low"
        ),
    }
