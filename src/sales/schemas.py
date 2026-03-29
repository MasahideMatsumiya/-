from typing import Optional

from pydantic import BaseModel

from src.sales.models import Channel


class CampaignCreate(BaseModel):
    name: str
    channel: Channel
    target_community: str
    message_template: str
    product_id: Optional[int] = None


class OutreachRecordCreate(BaseModel):
    campaign_id: int
    channel: Channel
    target_handle: str
    message_sent: str


class ChannelCreate(BaseModel):
    name: str
    channel: Channel
    url: str
    description: str
    member_count: Optional[int] = None
    ai_focus: bool = True
    language: str = "en"
