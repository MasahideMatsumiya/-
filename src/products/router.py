"""商材CRUD API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.database import get_session
from src.products.models import Product, ProductCategory, ProductStatus
from src.products.schemas import ProductCreate, ProductPublic, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


@router.get("/", response_model=list[ProductPublic])
async def list_products(
    category: Optional[ProductCategory] = None,
    min_price: float = 0,
    max_price: float = 50,
    search: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """商材一覧（公開用）"""
    query = select(Product).where(Product.status == ProductStatus.ACTIVE)
    if category:
        query = query.where(Product.category == category)
    query = query.where(Product.price_usd >= min_price, Product.price_usd <= max_price)
    if search:
        query = query.where(Product.name.contains(search) | Product.description.contains(search))
    query = query.offset(offset).limit(limit).order_by(Product.sales_count.desc())
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/{slug}", response_model=ProductPublic)
async def get_product(slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Product).where(Product.slug == slug))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    product.view_count += 1
    session.add(product)
    await session.commit()
    return product


def _slugify(text: str) -> str:
    import re
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "-", text) or "product"


@router.post("/", response_model=ProductPublic)
async def create_product(data: ProductCreate, session: AsyncSession = Depends(get_session)):
    """新商材登録"""
    slug = _slugify(data.name)
    product = Product(**data.model_dump(), slug=slug)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductPublic)
async def update_product(
    product_id: int, data: ProductUpdate, session: AsyncSession = Depends(get_session)
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(product, key, val)
    session.add(product)
    await session.commit()
    return product
