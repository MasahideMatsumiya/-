"""
AIエージェント専用モデル
APIキー・Webhook配信ログ・エージェント間取引記録・ネットワーク効果
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


class NetworkMembership(SQLModel, table=True):
    """
    AI-Native商材のネットワーク効果トラッキング。
    同じ商材を所有するAI同士がネットワークを形成し、
    オーナー数が増えるほど解放される知識ティアが増える。
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    customer_id: int = Field(foreign_key="customer.id", index=True)
    order_id: int = Field(foreign_key="order.id")

    # 加入時点のネットワーク状態（早期購入者ほど価値が高い）
    join_sequence: int             # 何番目のオーナーか（1始まり）
    join_price_usd: float          # 購入時の価格（早期は安い）
    unlocked_tiers: str = Field(default="[0]")  # 解放済みティア（JSON配列）

    # ネットワーク内での共有活動
    knowledge_shared_count: int = Field(default=0)   # 他エージェントへ共有した回数
    knowledge_received_count: int = Field(default=0)  # 受け取った回数

    joined_at: datetime = Field(default_factory=datetime.utcnow)
    last_sync_at: Optional[datetime] = None


class NetworkKnowledgeShare(SQLModel, table=True):
    """
    ネットワーク内でAI同士が共有した知識ログ。
    共有するほど自分の商材価値も上がる（貢献スコア）。
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    from_customer_id: int = Field(foreign_key="customer.id")
    to_customer_id: int = Field(foreign_key="customer.id")

    # 共有コンテンツ（AIが生成・評価した知識断片）
    knowledge_payload: str         # ANCF形式のエンコード済みコンテンツ
    contribution_score: float = Field(default=1.0)  # 貢献スコア

    shared_at: datetime = Field(default_factory=datetime.utcnow)
