"""商材CRUD API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.database import get_session
from src.products.models import Product, ProductCategory, ProductStatus
from src.products.schemas import ProductCreate, ProductPublic, ProductUpdate

MAX_BULK = 30  # 1リクエストで作成できる最大数

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


@router.post("/bulk", response_model=list[ProductPublic])
async def create_products_bulk(
    items: list[ProductCreate],
    session: AsyncSession = Depends(get_session),
):
    """
    商材一括登録（最大30件/リクエスト）。
    1日10〜30種類の商材を効率投入するためのエンドポイント。
    スラッグが重複した場合は連番サフィックスを付与。
    """
    if len(items) > MAX_BULK:
        raise HTTPException(400, f"最大{MAX_BULK}件まで一括登録可能です")
    if len(items) == 0:
        raise HTTPException(400, "1件以上指定してください")

    # 既存スラッグを一括取得して重複回避
    base_slugs = [_slugify(item.name) for item in items]
    existing_result = await session.execute(
        select(Product.slug).where(Product.slug.in_(base_slugs))
    )
    existing_slugs = {row[0] for row in existing_result.all()}

    created = []
    slug_counter: dict[str, int] = {}
    for item in items:
        base = _slugify(item.name)
        candidate = base
        count = slug_counter.get(base, 0)
        while candidate in existing_slugs:
            count += 1
            candidate = f"{base}-{count}"
        slug_counter[base] = count
        existing_slugs.add(candidate)

        product = Product(**item.model_dump(), slug=candidate)
        session.add(product)
        created.append(product)

    await session.commit()
    for p in created:
        await session.refresh(p)
    return created


@router.get("/{slug}/recommendations", response_model=list[ProductPublic])
async def get_recommendations(
    slug: str,
    limit: int = Query(default=5, le=10),
    session: AsyncSession = Depends(get_session),
):
    """
    アップセル・クロスセル推薦（同カテゴリ内の売れ筋商材）。
    購入後のフォローアップメールや商品ページのサイドバーで活用。
    """
    result = await session.execute(select(Product).where(Product.slug == slug))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")

    recs_result = await session.execute(
        select(Product)
        .where(
            Product.status == ProductStatus.ACTIVE,
            Product.category == product.category,
            Product.id != product.id,
        )
        .order_by(Product.sales_count.desc())
        .limit(limit)
    )
    return recs_result.scalars().all()
