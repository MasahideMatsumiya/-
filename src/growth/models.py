"""
成長KPIモジュール
日次スナップショット・LTV計算・成長率・ファネル分析
"""
from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class DailySnapshot(SQLModel, table=True):
    """日次KPIスナップショット（毎日1回記録）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_date: date = Field(unique=True, index=True)

    # 販売
    orders_count: int = Field(default=0)       # 当日注文数
    revenue_usd: float = Field(default=0.0)    # 当日売上
    new_customers: int = Field(default=0)      # 当日新規顧客数
    repeat_orders: int = Field(default=0)      # リピート購入数

    # 成長率
    growth_rate_pct: float = Field(default=0.0)  # 前日比 (105.0 = 105%)
    mom_growth_pct: float = Field(default=0.0)   # 前月比

    # 顧客価値
    ltv_avg_usd: float = Field(default=0.0)    # 顧客平均LTV
    ltv_vip_usd: float = Field(default=0.0)    # VIP顧客平均LTV
    arpu_usd: float = Field(default=0.0)       # 1日の顧客当たり平均売上

    # ファネル
    product_views: int = Field(default=0)      # 商品ページビュー合計
    checkout_count: int = Field(default=0)     # チェックアウト開始数
    conversion_rate_pct: float = Field(default=0.0)  # view→購入転換率

    # 商材
    products_published: int = Field(default=0)  # 当日公開商材数

    created_at: datetime = Field(default_factory=datetime.utcnow)
