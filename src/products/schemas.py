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
    status: ProductStatus = ProductStatus.DRAFT
    preview_content: Optional[str] = None
    download_url: Optional[str] = None
    file_size_kb: Optional[int] = None
    tags: str = ""
    ai_models: str = ""
    language: str = "ja"
    # AI-Native動的価格
    pricing_model: str = "fixed"
    base_price_usd: Optional[float] = None
    price_step: int = 100
    # AI-Nativeコンテンツ
    content_format: str = "human"
    ai_decode_seed: Optional[str] = None
    network_value_enabled: bool = False


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
    pricing_model: str
    base_price_usd: Optional[float]
    price_step: int
    content_format: str
    network_value_enabled: bool

    class Config:
        from_attributes = True
