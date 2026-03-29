"""
商材モデル / Product Models
AIコミュニティ向けデジタル商材（$10前後）
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class ProductCategory(str, Enum):
    PROMPT = "prompt"           # プロンプトテンプレート
    DATASET = "dataset"         # データセット
    TOOL = "tool"               # AIツール/スクリプト
    GUIDE = "guide"             # ガイド/ハウツー
    AGENT = "agent"             # AIエージェント設定
    FINE_TUNE = "fine_tune"     # ファインチューニングデータ
    WORKFLOW = "workflow"       # n8n/Zapier等ワークフロー


class ProductStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str = Field(max_length=200)
    description: str
    short_description: str = Field(max_length=500)
    category: ProductCategory
    status: ProductStatus = Field(default=ProductStatus.DRAFT)

    # 価格（$10前後）
    price_usd: float = Field(default=10.0)
    compare_price_usd: Optional[float] = None  # 元値（割引表示用）
    stripe_price_id: Optional[str] = None

    # コンテンツ
    preview_content: Optional[str] = None  # 無料プレビュー部分
    download_url: Optional[str] = None     # 購入後ダウンロードURL
    file_size_kb: Optional[int] = None

    # メタデータ
    tags: str = Field(default="")  # comma-separated
    ai_models: str = Field(default="")  # 対応AIモデル (GPT-4, Claude, etc.)
    language: str = Field(default="ja")

    # 統計
    sales_count: int = Field(default=0)
    view_count: int = Field(default=0)
    rating_avg: float = Field(default=0.0)
    rating_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relations
    reviews: list["ProductReview"] = Relationship(back_populates="product")


class ProductReview(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id")
    customer_id: int = Field(foreign_key="customer.id")
    rating: int = Field(ge=1, le=5)
    title: str = Field(max_length=200)
    body: str
    verified_purchase: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    product: Optional[Product] = Relationship(back_populates="reviews")
