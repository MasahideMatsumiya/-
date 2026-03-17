from typing import Optional

from pydantic import BaseModel

from src.crm.models import CustomerSegment


class CustomerCreate(BaseModel):
    email: str
    name: Optional[str] = None
    country: str = "JP"
    language: str = "ja"
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    segment: Optional[CustomerSegment] = None


class CustomerPublic(BaseModel):
    id: int
    email: str
    name: Optional[str]
    country: str
    segment: CustomerSegment
    total_orders: int
    total_spent_usd: float
    email_subscribed: bool
    referrer: Optional[str]

    class Config:
        from_attributes = True
