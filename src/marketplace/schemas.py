from typing import Optional

from pydantic import BaseModel

from src.marketplace.models import OrderStatus, PaymentMethod


class CheckoutRequest(BaseModel):
    customer_id: int
    product_id: int
    coupon_code: Optional[str] = None


class CheckoutResponse(BaseModel):
    order_id: int
    order_number: str
    total_usd: float
    stripe_client_secret: Optional[str] = None


class OrderPublic(BaseModel):
    id: int
    order_number: str
    product_id: int
    subtotal_usd: float
    discount_usd: float
    tax_usd: float
    total_usd: float
    status: OrderStatus
    payment_method: PaymentMethod
    download_count: int
    paid_at: Optional[object] = None

    class Config:
        from_attributes = True
