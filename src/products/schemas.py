from typing import Optional

from pydantic import BaseModel

from src.products.models import ProductCategory, ProductStatus


class ProductCreate(BaseModel):
    name: str
    description: str
    short_description: str
    category: ProductCategory
    price_usd: float = 10.0
    compare_price_usd: Optional[float] = None
    preview_content: Optional[str] = None
    tags: str = ""
    ai_models: str = ""
    language: str = "ja"


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    price_usd: Optional[float] = None
    status: Optional[ProductStatus] = None
    tags: Optional[str] = None


class ProductPublic(BaseModel):
    id: int
    slug: str
    name: str
    short_description: str
    category: ProductCategory
    status: ProductStatus
    price_usd: float
    compare_price_usd: Optional[float]
    preview_content: Optional[str]
    tags: str
    ai_models: str
    sales_count: int
    rating_avg: float
    rating_count: int

    class Config:
        from_attributes = True
