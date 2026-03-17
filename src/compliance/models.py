"""
取引法コンプライアンスモデル
特定商取引法・資金決済法・GDPR・利用規約管理
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class LegalDocument(SQLModel, table=True):
    """法的文書（利用規約・プライバシーポリシー等）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    doc_type: str  # "terms", "privacy", "tokushoho", "refund_policy"
    version: str   # "1.0", "1.1"
    title: str
    content: str
    is_current: bool = Field(default=True)
    effective_date: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CustomerConsent(SQLModel, table=True):
    """顧客同意記録（GDPR・特定商取引法）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    doc_type: str
    doc_version: str
    agreed: bool = Field(default=True)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    agreed_at: datetime = Field(default_factory=datetime.utcnow)


class RefundRequest(SQLModel, table=True):
    """返金申請（特定商取引法・クーリングオフ対応）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    customer_id: int = Field(foreign_key="customer.id")
    reason: str
    status: str = Field(default="pending")  # "pending", "approved", "rejected"
    refund_amount_usd: Optional[float] = None
    stripe_refund_id: Optional[str] = None
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    processed_at: Optional[datetime] = None
    notes: Optional[str] = None
