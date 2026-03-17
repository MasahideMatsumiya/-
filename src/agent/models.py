"""
AIエージェント専用モデル
APIキー・Webhook配信ログ・エージェント間取引記録
"""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AgentDeliveryLog(SQLModel, table=True):
    """
    購入後のWebhook配信ログ
    email代わりにcallback_urlへPOSTで商材を届ける
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    customer_id: int = Field(foreign_key="customer.id")
    callback_url: str
    payload_summary: str          # 配信したペイロードのサマリー（JSON）
    status: str = Field(default="pending")  # pending|delivered|failed|retrying
    http_status: Optional[int] = None
    attempt_count: int = Field(default=0)
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentApiKey(SQLModel, table=True):
    """
    エージェント用APIキー（プレーンキーはここには保存しない。customer.api_key_hashで管理）
    ローテーション履歴・スコープ管理用
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id", index=True)
    key_prefix: str               # 表示用プレフィックス (例: "ak_live_abc123...")
    key_hash: str = Field(index=True)  # SHA256ハッシュ
    scopes: str = Field(default='["catalog:read","checkout"]')  # JSON配列
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
