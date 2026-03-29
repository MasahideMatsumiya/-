"""営業管理API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.database import get_session
from src.sales.models import CommunityChannel, OutreachCampaign, OutreachRecord, OutreachStatus
from src.sales.schemas import CampaignCreate, ChannelCreate, OutreachRecordCreate

router = APIRouter(prefix="/sales", tags=["sales"])

# --- コミュニティチャンネル管理 ---
@router.get("/channels", response_model=list[dict])
async def list_channels(session: AsyncSession = Depends(get_session)):
    """営業先AIコミュニティ一覧"""
    result = await session.execute(
        select(CommunityChannel).where(CommunityChannel.is_active)
    )
    return [r.model_dump() for r in result.scalars().all()]


@router.post("/channels")
async def add_channel(data: ChannelCreate, session: AsyncSession = Depends(get_session)):
    channel = CommunityChannel(**data.model_dump())
    session.add(channel)
    await session.commit()
    await session.refresh(channel)
    return channel


# --- キャンペーン管理 ---
@router.get("/campaigns")
async def list_campaigns(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OutreachCampaign))
    return [r.model_dump() for r in result.scalars().all()]


@router.post("/campaigns")
async def create_campaign(data: CampaignCreate, session: AsyncSession = Depends(get_session)):
    campaign = OutreachCampaign(**data.model_dump())
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.get("/campaigns/{campaign_id}/stats")
async def campaign_stats(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await session.get(OutreachCampaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    response_rate = (
        campaign.response_count / campaign.sent_count * 100 if campaign.sent_count > 0 else 0
    )
    conversion_rate = (
        campaign.conversion_count / campaign.sent_count * 100 if campaign.sent_count > 0 else 0
    )
    return {
        "campaign": campaign.name,
        "sent": campaign.sent_count,
        "responses": campaign.response_count,
        "conversions": campaign.conversion_count,
        "revenue_usd": campaign.revenue_usd,
        "response_rate_pct": round(response_rate, 2),
        "conversion_rate_pct": round(conversion_rate, 2),
        "roi_usd": campaign.revenue_usd,
    }


# --- 個別アウトリーチ記録 ---
@router.post("/outreach")
async def record_outreach(
    data: OutreachRecordCreate, session: AsyncSession = Depends(get_session)
):
    record = OutreachRecord(**data.model_dump())
    session.add(record)
    # キャンペーン集計更新
    campaign = await session.get(OutreachCampaign, data.campaign_id)
    if campaign:
        campaign.sent_count += 1
        session.add(campaign)
    await session.commit()
    return {"status": "recorded", "id": record.id}


@router.patch("/outreach/{record_id}/convert")
async def mark_converted(
    record_id: int, order_id: int, session: AsyncSession = Depends(get_session)
):
    record = await session.get(OutreachRecord, record_id)
    if not record:
        raise HTTPException(404, "Record not found")
    record.status = OutreachStatus.CONVERTED
    record.converted_order_id = order_id
    campaign = await session.get(OutreachCampaign, record.campaign_id)
    if campaign:
        campaign.conversion_count += 1
        session.add(campaign)
    session.add(record)
    await session.commit()
    return {"status": "converted"}
