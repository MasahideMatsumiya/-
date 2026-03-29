"""
顧客管理 (CRM) Models
顧客情報・購入履歴・セグメント・メールリスト管理
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class CustomerSegment(str, Enum):
    NEW = "new"                   # 新規
    REPEAT = "repeat"             # リピーター
    VIP = "vip"                   # VIP (3件以上購入)
    CHURNED = "churned"           # 離脱（90日以上未購入）
    PROSPECT = "prospect"         # 見込み客（メールリストのみ）


class AgentFramework(str, Enum):
    """AIエージェントフレームワーク種別"""
    LANGCHAIN = "langchain"
    AUTOGPT = "autogpt"
    CREWAI = "crewai"
    OPENAI_ASSISTANT = "openai_assistant"
    DIFY = "dify"
    N8N = "n8n"
    FLOWISE = "flowise"
    MASTRA = "mastra"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class Customer(SQLModel, table=True):
    """顧客マスタ（人間 & AIエージェント 両対応）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: Optional[str] = None
    country: str = Field(default="JP")
    language: str = Field(default="ja")
    segment: CustomerSegment = Field(default=CustomerSegment.NEW)

    # ---- AIエージェント専用フィールド ----
    is_agent: bool = Field(default=False)                         # エージェント顧客フラグ
    agent_framework: Optional[AgentFramework] = None             # 使用フレームワーク
    agent_version: Optional[str] = None                          # エージェントバージョン
    agent_owner_handle: Optional[str] = None                     # オーナーの@ハンドル
    api_key_hash: Optional[str] = Field(default=None, index=True)  # APIキー（SHA256ハッシュ）
    callback_url: Optional[str] = None                           # 購入後に配信するWebhook URL
    agent_capabilities: str = Field(default="[]")  # JSON: ["text_gen","code","search"]
    last_api_call_at: Optional[datetime] = None                  # 最終API呼び出し日時

    # 購買統計
    total_orders: int = Field(default=0)
    total_spent_usd: float = Field(default=0.0)
    avg_order_usd: float = Field(default=0.0)
    last_purchase_at: Optional[datetime] = None

    # メール設定（人間顧客向け）
    email_subscribed: bool = Field(default=True)
    email_unsubscribed_at: Optional[datetime] = None

    # 認証
    hashed_password: Optional[str] = None
    is_active: bool = Field(default=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # リファラ
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None

    # 不正リスク管理
    refund_count: int = Field(default=0)
    fraud_flagged: bool = Field(default=False)
    fraud_flagged_at: Optional[datetime] = None
    fraud_reason: Optional[str] = None


class EmailTemplate(SQLModel, table=True):
    """メールテンプレート"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    subject: str
    body_html: str
    body_text: str
    trigger: str  # "welcome", "purchase", "followup_3d", "followup_7d", "newsletter"
    is_active: bool = Field(default=True)


class EmailLog(SQLModel, table=True):
    """メール送信ログ"""
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    template_id: Optional[int] = Field(default=None, foreign_key="emailtemplate.id")
    subject: str
    status: str = Field(default="sent")  # "sent", "bounced", "opened", "clicked"
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class Tag(SQLModel, table=True):
    """顧客タグ（関心領域管理）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    customer_id: int = Field(foreign_key="customer.id")
    tag: str  # "interested_prompt", "ai_developer", "marketer", etc.
