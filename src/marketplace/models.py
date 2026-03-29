"""
取引所 / Marketplace Models
注文・決済・ダウンロード管理
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class OrderStatus(str, Enum):
    PENDING = "pending"         # 決済待ち
    PAID = "paid"               # 決済完了
    DELIVERED = "delivered"     # 商品配信済み
    REFUNDED = "refunded"       # 返金済み
    DISPUTED = "disputed"       # 異議申し立て中


class PaymentMethod(str, Enum):
    STRIPE = "stripe"
    PAYPAL = "paypal"
    CRYPTO = "crypto"           # 将来対応


class Order(SQLModel, table=True):
    """注文（取引）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_number: str = Field(unique=True, index=True)  # ORD-2024-000001
    customer_id: int = Field(foreign_key="customer.id")
    product_id: int = Field(foreign_key="product.id")

    # 価格明細
    subtotal_usd: float
    discount_usd: float = Field(default=0.0)
    tax_usd: float = Field(default=0.0)
    total_usd: float
    platform_fee_usd: float       # プラットフォーム手数料 (10%)
    seller_revenue_usd: float     # 販売者取り分

    # 決済
    payment_method: PaymentMethod = Field(default=PaymentMethod.STRIPE)
    stripe_payment_intent_id: Optional[str] = None
    stripe_charge_id: Optional[str] = None

    status: OrderStatus = Field(default=OrderStatus.PENDING)
    coupon_code: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    # 配信
    download_token: Optional[str] = None   # 購入後ダウンロード用トークン
    download_expires_at: Optional[datetime] = None
    download_count: int = Field(default=0)
    max_downloads: int = Field(default=5)

    paid_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Coupon(SQLModel, table=True):
    """クーポン・割引コード"""
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)
    discount_type: str  # "percent" | "fixed"
    discount_value: float
    min_order_usd: float = Field(default=0.0)
    max_uses: Optional[int] = None
    used_count: int = Field(default=0)
    valid_from: datetime = Field(default_factory=datetime.utcnow)
    valid_until: Optional[datetime] = None
    is_active: bool = Field(default=True)


class DownloadLog(SQLModel, table=True):
    """ダウンロード履歴"""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    ip_address: str
    downloaded_at: datetime = Field(default_factory=datetime.utcnow)
