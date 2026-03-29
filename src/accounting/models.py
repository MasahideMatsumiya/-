"""
経理モデル / Accounting Models
売上・手数料・税務・帳簿管理
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class TransactionType(str, Enum):
    SALE = "sale"               # 売上
    REFUND = "refund"           # 返金
    PLATFORM_FEE = "platform_fee"  # プラットフォーム手数料
    STRIPE_FEE = "stripe_fee"   # Stripe決済手数料 (~2.9% + $0.30)
    PAYOUT = "payout"           # 出金


class LedgerEntry(SQLModel, table=True):
    """仕訳帳（複式簿記）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[int] = Field(default=None, foreign_key="order.id")
    transaction_type: TransactionType
    amount_usd: float
    tax_usd: float = Field(default=0.0)
    net_usd: float             # amount_usd - tax_usd

    # 勘定科目
    debit_account: str          # 借方（例: "売掛金", "現金"）
    credit_account: str         # 貸方（例: "売上", "消費税預り金"）
    description: str

    reference_id: Optional[str] = None  # Stripe charge ID 等
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    fiscal_year: int
    fiscal_month: int


class MonthlySummary(SQLModel, table=True):
    """月次サマリー"""
    id: Optional[int] = Field(default=None, primary_key=True)
    year: int
    month: int
    gross_revenue_usd: float = Field(default=0.0)
    refunds_usd: float = Field(default=0.0)
    net_revenue_usd: float = Field(default=0.0)
    platform_fees_usd: float = Field(default=0.0)
    stripe_fees_usd: float = Field(default=0.0)
    tax_collected_usd: float = Field(default=0.0)
    orders_count: int = Field(default=0)
    refunds_count: int = Field(default=0)
    new_customers: int = Field(default=0)
    calculated_at: datetime = Field(default_factory=datetime.utcnow)
