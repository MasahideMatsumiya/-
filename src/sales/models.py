"""
AIコミュニティ営業モデル / Sales & Outreach Models
Discord, Reddit, Twitter(X), Hacker News 等AIコミュニティへの営業管理
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class Channel(str, Enum):
    DISCORD = "discord"
    REDDIT = "reddit"
    TWITTER = "twitter"
    HACKERNEWS = "hackernews"
    GITHUB = "github"
    LINKEDIN = "linkedin"
    EMAIL = "email"
    DIRECT = "direct"


class OutreachStatus(str, Enum):
    PLANNED = "planned"
    SENT = "sent"
    RESPONDED = "responded"
    CONVERTED = "converted"
    DECLINED = "declined"


class OutreachCampaign(SQLModel, table=True):
    """営業キャンペーン管理"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    channel: Channel
    target_community: str          # 例: "r/MachineLearning", "Discord: AI Builders"
    message_template: str          # メッセージテンプレート
    product_id: Optional[int] = Field(default=None, foreign_key="product.id")

    # 実績
    sent_count: int = Field(default=0)
    response_count: int = Field(default=0)
    conversion_count: int = Field(default=0)
    revenue_usd: float = Field(default=0.0)

    status: str = Field(default="active")
    scheduled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OutreachRecord(SQLModel, table=True):
    """個別営業記録"""
    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="outreachcampaign.id")
    channel: Channel
    target_handle: str             # @username, username, URL等
    message_sent: str
    status: OutreachStatus = Field(default=OutreachStatus.PLANNED)
    response_received: Optional[str] = None
    converted_order_id: Optional[int] = None
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None


class CommunityChannel(SQLModel, table=True):
    """コミュニティチャンネル一覧（営業先リスト）"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    channel: Channel
    url: str
    description: str
    member_count: Optional[int] = None
    ai_focus: bool = Field(default=True)
    language: str = Field(default="en")  # 主要言語
    avg_engagement: Optional[float] = None  # 平均エンゲージメント率
    last_posted_at: Optional[datetime] = None
    is_active: bool = Field(default=True)
