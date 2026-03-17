"""経理・会計API"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from src.accounting.models import LedgerEntry, MonthlySummary, TransactionType
from src.database import get_session
from src.marketplace.models import Order, OrderStatus

router = APIRouter(prefix="/accounting", tags=["accounting"])

# Stripe 手数料: 2.9% + $0.30
STRIPE_FEE_RATE = 0.029
STRIPE_FEE_FIXED = 0.30


@router.post("/record-sale/{order_id}")
async def record_sale(order_id: int, session: AsyncSession = Depends(get_session)):
    """注文確定時の仕訳記録"""
    order = await session.get(Order, order_id)
    if not order:
        return {"error": "Order not found"}

    now = datetime.utcnow()
    stripe_fee = order.total_usd * STRIPE_FEE_RATE + STRIPE_FEE_FIXED

    # 1. 売上仕訳
    entries = [
        LedgerEntry(
            order_id=order_id,
            transaction_type=TransactionType.SALE,
            amount_usd=order.subtotal_usd,
            tax_usd=order.tax_usd,
            net_usd=order.subtotal_usd,
            debit_account="現金・預金",
            credit_account="売上高",
            description=f"商品販売 Order#{order.order_number}",
            reference_id=order.stripe_charge_id,
            fiscal_year=now.year,
            fiscal_month=now.month,
        ),
        LedgerEntry(
            order_id=order_id,
            transaction_type=TransactionType.PLATFORM_FEE,
            amount_usd=order.platform_fee_usd,
            tax_usd=0,
            net_usd=order.platform_fee_usd,
            debit_account="支払手数料（プラットフォーム）",
            credit_account="現金・預金",
            description=f"プラットフォーム手数料 Order#{order.order_number}",
            fiscal_year=now.year,
            fiscal_month=now.month,
        ),
        LedgerEntry(
            order_id=order_id,
            transaction_type=TransactionType.STRIPE_FEE,
            amount_usd=stripe_fee,
            tax_usd=0,
            net_usd=stripe_fee,
            debit_account="支払手数料（決済）",
            credit_account="現金・預金",
            description=f"Stripe手数料 Order#{order.order_number}",
            fiscal_year=now.year,
            fiscal_month=now.month,
        ),
    ]
    for e in entries:
        session.add(e)
    await session.commit()
    return {"status": "recorded", "entries": len(entries)}


@router.get("/monthly/{year}/{month}")
async def monthly_report(
    year: int, month: int, session: AsyncSession = Depends(get_session)
):
    """月次損益レポート"""
    result = await session.execute(
        select(MonthlySummary).where(
            MonthlySummary.year == year, MonthlySummary.month == month
        )
    )
    summary = result.scalar_one_or_none()

    if not summary:
        # リアルタイム集計
        orders_result = await session.execute(
            select(Order).where(
                Order.status == OrderStatus.PAID,
                func.extract("year", Order.paid_at) == year,
                func.extract("month", Order.paid_at) == month,
            )
        )
        orders = orders_result.scalars().all()
        gross = sum(o.total_usd for o in orders)
        stripe_fees = sum(o.total_usd * STRIPE_FEE_RATE + STRIPE_FEE_FIXED for o in orders)
        platform_fees = sum(o.platform_fee_usd for o in orders)
        tax = sum(o.tax_usd for o in orders)

        return {
            "year": year,
            "month": month,
            "gross_revenue_usd": round(gross, 2),
            "platform_fees_usd": round(platform_fees, 2),
            "stripe_fees_usd": round(stripe_fees, 2),
            "tax_collected_usd": round(tax, 2),
            "net_revenue_usd": round(gross - platform_fees - stripe_fees, 2),
            "orders_count": len(orders),
            "avg_order_usd": round(gross / len(orders), 2) if orders else 0,
        }
    return summary.model_dump()


@router.get("/dashboard")
async def accounting_dashboard(session: AsyncSession = Depends(get_session)):
    """経営ダッシュボード（累計・今月・先月）"""
    now = datetime.utcnow()

    # 累計売上
    total_result = await session.execute(
        select(func.sum(Order.total_usd), func.count(Order.id)).where(
            Order.status == OrderStatus.PAID
        )
    )
    total_rev, total_orders = total_result.one()

    # 今月
    this_month = await session.execute(
        select(func.sum(Order.total_usd), func.count(Order.id)).where(
            Order.status == OrderStatus.PAID,
            func.extract("year", Order.paid_at) == now.year,
            func.extract("month", Order.paid_at) == now.month,
        )
    )
    month_rev, month_orders = this_month.one()

    return {
        "total_revenue_usd": round(total_rev or 0, 2),
        "total_orders": total_orders or 0,
        "this_month_revenue_usd": round(month_rev or 0, 2),
        "this_month_orders": month_orders or 0,
        "avg_order_value_usd": round((total_rev or 0) / (total_orders or 1), 2),
    }


@router.get("/ledger")
async def get_ledger(
    year: int = Query(default=datetime.utcnow().year),
    month: int = Query(default=datetime.utcnow().month),
    session: AsyncSession = Depends(get_session),
):
    """仕訳帳出力（CSV/会計ソフト連携用）"""
    result = await session.execute(
        select(LedgerEntry).where(
            LedgerEntry.fiscal_year == year, LedgerEntry.fiscal_month == month
        ).order_by(LedgerEntry.recorded_at)
    )
    entries = result.scalars().all()
    return [e.model_dump() for e in entries]
