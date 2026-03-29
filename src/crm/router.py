"""顧客管理API"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from src.crm.models import Customer, CustomerSegment, Tag
from src.crm.schemas import CustomerCreate, CustomerPublic, CustomerUpdate
from src.database import get_session

router = APIRouter(prefix="/crm", tags=["crm"])


@router.post("/customers", response_model=CustomerPublic)
async def create_customer(data: CustomerCreate, session: AsyncSession = Depends(get_session)):
    existing = await session.execute(select(Customer).where(Customer.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email already registered")
    customer = Customer(**data.model_dump())
    session.add(customer)
    await session.commit()
    await session.refresh(customer)
    return customer


@router.get("/customers/by-email", response_model=CustomerPublic)
async def get_customer_by_email(email: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Customer).where(Customer.email == email))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(404, "Customer not found")
    return customer


@router.get("/customers/{customer_id}", response_model=CustomerPublic)
async def get_customer(customer_id: int, session: AsyncSession = Depends(get_session)):
    customer = await session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    return customer


@router.patch("/customers/{customer_id}", response_model=CustomerPublic)
async def update_customer(
    customer_id: int, data: CustomerUpdate, session: AsyncSession = Depends(get_session)
):
    customer = await session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(customer, key, val)
    customer.updated_at = datetime.utcnow()
    session.add(customer)
    await session.commit()
    return customer


@router.post("/customers/{customer_id}/tags")
async def add_tag(customer_id: int, tag: str, session: AsyncSession = Depends(get_session)):
    t = Tag(customer_id=customer_id, tag=tag)
    session.add(t)
    await session.commit()
    return {"status": "tagged"}


@router.get("/segments/summary")
async def segment_summary(session: AsyncSession = Depends(get_session)):
    """セグメント別顧客数サマリー"""
    result = await session.execute(
        select(Customer.segment, func.count(Customer.id)).group_by(Customer.segment)
    )
    return {seg: count for seg, count in result.all()}


@router.get("/customers/{customer_id}/history")
async def purchase_history(customer_id: int, session: AsyncSession = Depends(get_session)):
    """購入履歴"""
    from src.marketplace.models import Order
    result = await session.execute(
        select(Order).where(Order.customer_id == customer_id).order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [{"order_number": o.order_number, "total_usd": o.total_usd, "status": o.status,
             "paid_at": o.paid_at} for o in orders]


async def update_customer_segment(customer: Customer, session: AsyncSession):
    """購入後にセグメント自動更新"""
    if customer.total_orders >= 3:
        customer.segment = CustomerSegment.VIP
    elif customer.total_orders >= 2:
        customer.segment = CustomerSegment.REPEAT
    elif customer.total_orders == 1:
        customer.segment = CustomerSegment.NEW

    if customer.last_purchase_at:
        days_since = (datetime.utcnow() - customer.last_purchase_at).days
        if days_since > 90 and customer.total_orders > 0:
            customer.segment = CustomerSegment.CHURNED

    session.add(customer)
    await session.commit()


@router.delete("/customers/{customer_id}/unsubscribe")
async def unsubscribe(customer_id: int, session: AsyncSession = Depends(get_session)):
    """メール配信停止（GDPR対応）"""
    customer = await session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    customer.email_subscribed = False
    customer.email_unsubscribed_at = datetime.utcnow()
    session.add(customer)
    await session.commit()
    return {"status": "unsubscribed"}
