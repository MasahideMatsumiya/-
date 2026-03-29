"""
成長KPI API
日次スナップショット・LTV・成長率・ファネル・目標管理
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from src.database import get_session
from src.growth.models import DailySnapshot

router = APIRouter(prefix="/growth", tags=["growth"])

# 目標値（環境変数化も可能）
TARGET_DAY1_ORDERS = 100
TARGET_DAILY_GROWTH_PCT = 105.0
TARGET_DAILY_PRODUCTS = 20


async def _compute_today_snapshot(session: AsyncSession) -> dict:
    """当日のKPIをリアルタイム計算"""
    from src.crm.models import Customer
    from src.marketplace.models import Order, OrderStatus
    from src.products.models import Product, ProductStatus

    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    # 当日注文
    orders_result = await session.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_usd), 0)).where(
            Order.status == OrderStatus.PAID,
            Order.paid_at >= today_start,
        )
    )
    orders_count, revenue_usd = orders_result.one()

    # 当日新規顧客
    new_customers_result = await session.execute(
        select(func.count(Customer.id)).where(Customer.created_at >= today_start)
    )
    new_customers = new_customers_result.scalar() or 0

    # リピート注文（過去購入ありの顧客による当日注文）
    repeat_result = await session.execute(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.PAID,
            Order.paid_at >= today_start,
            Order.customer_id.in_(
                select(Order.customer_id)
                .where(Order.status == OrderStatus.PAID, Order.paid_at < today_start)
                .distinct()
            ),
        )
    )
    repeat_orders = repeat_result.scalar() or 0

    # 商品ビュー
    views_result = await session.execute(select(func.coalesce(func.sum(Product.view_count), 0)))
    total_views = views_result.scalar() or 0

    # 当日公開商材
    products_result = await session.execute(
        select(func.count(Product.id)).where(
            Product.status == ProductStatus.ACTIVE,
            Product.created_at >= today_start,
        )
    )
    products_published = products_result.scalar() or 0

    # チェックアウト数（PENDING含む）
    checkout_result = await session.execute(
        select(func.count(Order.id)).where(Order.created_at >= today_start)
    )
    checkout_count = checkout_result.scalar() or 0

    conversion_rate = (orders_count / total_views * 100) if total_views > 0 else 0.0

    return {
        "date": today.isoformat(),
        "orders_count": orders_count,
        "revenue_usd": round(float(revenue_usd), 2),
        "new_customers": new_customers,
        "repeat_orders": repeat_orders,
        "products_published": products_published,
        "checkout_count": checkout_count,
        "conversion_rate_pct": round(conversion_rate, 2),
    }


async def _calc_ltv(session: AsyncSession) -> dict:
    """LTV計算（セグメント別）"""
    from src.crm.models import Customer, CustomerSegment

    result = await session.execute(
        select(
            Customer.segment,
            func.count(Customer.id),
            func.coalesce(func.avg(Customer.total_spent_usd), 0),
            func.coalesce(func.max(Customer.total_spent_usd), 0),
        ).where(Customer.total_orders > 0).group_by(Customer.segment)
    )
    rows = result.all()

    ltv_by_segment = {}
    total_avg = 0.0
    total_count = 0
    for segment, count, avg_spent, max_spent in rows:
        ltv_by_segment[segment] = {
            "count": count,
            "avg_ltv_usd": round(float(avg_spent), 2),
            "max_ltv_usd": round(float(max_spent), 2),
            # 予測LTV = 現在の平均 × リテンション係数（VIPは3倍、REPEATは2倍、NEWは1倍）
            "predicted_ltv_usd": round(float(avg_spent) * {
                CustomerSegment.VIP: 5.0,
                CustomerSegment.REPEAT: 2.5,
                CustomerSegment.NEW: 1.2,
                CustomerSegment.CHURNED: 0.5,
            }.get(segment, 1.0), 2),
        }
        total_avg += float(avg_spent) * count
        total_count += count

    overall_avg = total_avg / total_count if total_count > 0 else 0.0
    return {"overall_avg_ltv_usd": round(overall_avg, 2), "by_segment": ltv_by_segment}


@router.get("/dashboard")
async def growth_dashboard(session: AsyncSession = Depends(get_session)):
    """
    成長KPIダッシュボード

    - 本日 vs 昨日の注文数・売上
    - 105%/日の目標達成率
    - 直近7日の推移
    - LTV（セグメント別）
    - 商材投入ペース
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    # 今日のリアルタイムKPI
    today_kpi = await _compute_today_snapshot(session)

    # 昨日のスナップショット（記録済みの場合）
    yesterday_snap = await session.execute(
        select(DailySnapshot).where(DailySnapshot.snapshot_date == yesterday)
    )
    yesterday_snap = yesterday_snap.scalar_one_or_none()
    yesterday_orders = yesterday_snap.orders_count if yesterday_snap else 0
    yesterday_revenue = yesterday_snap.revenue_usd if yesterday_snap else 0.0

    # 成長率計算
    growth_rate = (
        today_kpi["orders_count"] / yesterday_orders * 100
        if yesterday_orders > 0 else None
    )

    # 目標達成率
    day1_achievement_pct = today_kpi["orders_count"] / TARGET_DAY1_ORDERS * 100
    growth_on_target = (
        growth_rate is not None and growth_rate >= TARGET_DAILY_GROWTH_PCT
    )

    # 直近7日スナップショット
    week_ago = today - timedelta(days=7)
    snapshots_result = await session.execute(
        select(DailySnapshot)
        .where(DailySnapshot.snapshot_date >= week_ago)
        .order_by(DailySnapshot.snapshot_date)
    )
    weekly = [
        {
            "date": s.snapshot_date.isoformat(),
            "orders": s.orders_count,
            "revenue_usd": s.revenue_usd,
            "growth_rate_pct": s.growth_rate_pct,
            "products_published": s.products_published,
        }
        for s in snapshots_result.scalars().all()
    ]

    # LTV
    ltv = await _calc_ltv(session)

    # 売上予測（105%成長を継続した場合の30日後）
    projected_30d = today_kpi["revenue_usd"]
    for _ in range(30):
        projected_30d *= TARGET_DAILY_GROWTH_PCT / 100

    return {
        "today": {
            **today_kpi,
            "growth_rate_pct": round(growth_rate, 1) if growth_rate else None,
            "growth_on_target": growth_on_target,
            "day1_achievement_pct": round(day1_achievement_pct, 1),
        },
        "yesterday": {
            "orders_count": yesterday_orders,
            "revenue_usd": round(yesterday_revenue, 2),
        },
        "targets": {
            "day1_orders": TARGET_DAY1_ORDERS,
            "daily_growth_pct": TARGET_DAILY_GROWTH_PCT,
            "daily_products": TARGET_DAILY_PRODUCTS,
        },
        "weekly_trend": weekly,
        "ltv": ltv,
        "projections": {
            "revenue_30d_if_on_target_usd": round(projected_30d, 2),
            "note": f"現在の売上を毎日{TARGET_DAILY_GROWTH_PCT}%成長させた場合の30日後",
        },
    }


@router.post("/snapshot")
async def record_snapshot(session: AsyncSession = Depends(get_session)):
    """
    本日のKPIスナップショットを記録（日次バッチジョブから呼ぶ）
    既存レコードがあれば上書き更新
    """
    today = date.today()
    today_kpi = await _compute_today_snapshot(session)

    # 昨日との比較
    yesterday = today - timedelta(days=1)
    yesterday_snap = await session.execute(
        select(DailySnapshot).where(DailySnapshot.snapshot_date == yesterday)
    )
    yesterday_snap = yesterday_snap.scalar_one_or_none()
    yesterday_orders = yesterday_snap.orders_count if yesterday_snap else 0
    growth_rate = (
        today_kpi["orders_count"] / yesterday_orders * 100
        if yesterday_orders > 0 else 0.0
    )

    ltv = await _calc_ltv(session)
    ltv_avg = ltv["overall_avg_ltv_usd"]
    ltv_vip = ltv["by_segment"].get("vip", {}).get("avg_ltv_usd", 0.0)

    # upsert
    existing = await session.execute(
        select(DailySnapshot).where(DailySnapshot.snapshot_date == today)
    )
    snap = existing.scalar_one_or_none()
    if not snap:
        snap = DailySnapshot(snapshot_date=today)

    snap.orders_count = today_kpi["orders_count"]
    snap.revenue_usd = today_kpi["revenue_usd"]
    snap.new_customers = today_kpi["new_customers"]
    snap.repeat_orders = today_kpi["repeat_orders"]
    snap.growth_rate_pct = round(growth_rate, 2)
    snap.products_published = today_kpi["products_published"]
    snap.checkout_count = today_kpi["checkout_count"]
    snap.conversion_rate_pct = today_kpi["conversion_rate_pct"]
    snap.ltv_avg_usd = ltv_avg
    snap.ltv_vip_usd = ltv_vip

    session.add(snap)
    await session.commit()
    await session.refresh(snap)
    return {"status": "recorded", "snapshot_id": snap.id, "date": snap.snapshot_date}


@router.get("/ltv")
async def ltv_report(session: AsyncSession = Depends(get_session)):
    """LTVレポート（セグメント別・改善アドバイス付き）"""
    ltv = await _calc_ltv(session)

    advice = []
    vip = ltv["by_segment"].get("vip", {})
    new = ltv["by_segment"].get("new", {})
    repeat = ltv["by_segment"].get("repeat", {})
    churned = ltv["by_segment"].get("churned", {})

    if new.get("count", 0) > 0 and repeat.get("count", 0) < new.get("count", 0) * 0.3:
        advice.append("新規顧客の30%未満しかリピートしていません。購入後3日・7日のフォローアップメールを強化してください。")
    if churned.get("count", 0) > 0:
        advice.append(f"離脱顧客が{churned['count']}人います。再エンゲージメントキャンペーン（クーポン配布）を検討してください。")
    if vip.get("count", 0) == 0:
        advice.append("VIP顧客がまだいません。3回購入でVIPとなるバンドル割引を設計してください。")
    if not advice:
        advice.append("LTVは順調です。引き続き高品質商材の継続投入と購入後フォローを維持してください。")

    return {**ltv, "improvement_advice": advice}


@router.get("/funnel")
async def funnel_report(
    days: int = Query(default=7, le=30),
    session: AsyncSession = Depends(get_session),
):
    """
    購買ファネル分析（直近N日）
    view → checkout → paid の転換率
    """
    from src.marketplace.models import Order, OrderStatus
    from src.products.models import Product

    since = datetime.utcnow() - timedelta(days=days)

    views_result = await session.execute(
        select(func.coalesce(func.sum(Product.view_count), 0))
    )
    total_views = int(views_result.scalar() or 0)

    checkouts_result = await session.execute(
        select(func.count(Order.id)).where(Order.created_at >= since)
    )
    checkouts = int(checkouts_result.scalar() or 0)

    paid_result = await session.execute(
        select(func.count(Order.id)).where(
            Order.status == OrderStatus.PAID, Order.paid_at >= since
        )
    )
    paid = int(paid_result.scalar() or 0)

    view_to_checkout = round(checkouts / total_views * 100, 2) if total_views > 0 else 0.0
    checkout_to_paid = round(paid / checkouts * 100, 2) if checkouts > 0 else 0.0
    overall = round(paid / total_views * 100, 2) if total_views > 0 else 0.0

    return {
        "period_days": days,
        "funnel": {
            "product_views": total_views,
            "checkout_started": checkouts,
            "orders_paid": paid,
        },
        "rates": {
            "view_to_checkout_pct": view_to_checkout,
            "checkout_to_paid_pct": checkout_to_paid,
            "overall_conversion_pct": overall,
        },
        "benchmark": {
            "view_to_checkout_target_pct": 5.0,
            "checkout_to_paid_target_pct": 70.0,
        },
    }
