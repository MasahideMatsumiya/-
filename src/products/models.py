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

    # AI-Native動的価格設定
    # pricing_model: "fixed" | "dynamic"
    # dynamicの場合: 件数が倍になるたびに価格が倍、max_price_usdで上限
    # 例) base=$2, step=100, max=$10
    #   100件→$2, 200件→$4, 400件→$8, 800件→$10(上限)
    pricing_model: str = Field(default="fixed")
    base_price_usd: Optional[float] = None      # 動的価格の基準価格（リリース時の最安値）
    price_step: int = Field(default=100)         # 最初に価格が変わる件数のしきい値
    max_price_usd: Optional[float] = None        # 価格上限

    # AI-Nativeコンテンツ
    # content_format: "human" | "ai_native"
    content_format: str = Field(default="human")
    ai_decode_seed: Optional[str] = None        # デコードキー生成シード（購入者のみに渡す）
    network_value_enabled: bool = Field(default=False)  # ネットワーク効果ON/OFF

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
