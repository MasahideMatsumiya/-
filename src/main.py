"""
AI Marketplace - メインアプリ
AIコミュニティ向けデジタル商材販売プラットフォーム ($10/商材)
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from src.accounting.router import router as accounting_router
from src.agent.router import router as agent_router
from src.compliance.router import router as compliance_router
from src.config import settings
from src.crm.router import router as crm_router
from src.database import get_session, init_db
from src.growth.router import router as growth_router
from src.marketplace.router import router as marketplace_router, stripe_webhook as _stripe_webhook
from src.products.router import router as products_router
from src.sales.router import router as sales_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AIコミュニティ向けデジタル商材マーケットプレイス",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全モジュールを登録
app.include_router(products_router)
app.include_router(sales_router)
app.include_router(marketplace_router)
app.include_router(crm_router)
app.include_router(compliance_router)
app.include_router(accounting_router)
app.include_router(growth_router)
app.include_router(agent_router)


@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "modules": [
            "products   - 商材管理（プロンプト・ツール・データセット等）",
            "sales      - AIコミュニティ営業管理",
            "marketplace - 取引所・決済（Stripe）",
            "crm        - 顧客管理",
            "compliance - 取引法・特定商取引法・GDPR",
            "accounting - 経理・会計",
            "growth     - 成長KPI・LTV・ファネル分析",
            "agent      - AIエージェント専用API（APIキー認証・Webhook配信・MCPマニフェスト）",
        ],
        "docs": "/docs",
    }


@app.get("/checkout")
async def checkout_page():
    """Stripe決済フォームページ"""
    return FileResponse(os.path.join(os.path.dirname(__file__), "../static/checkout.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


# /webhook/stripe のエイリアス（Stripeに登録したURLが /marketplace プレフィックスなしの場合に対応）
@app.post("/webhook/stripe")
async def webhook_stripe_alias(request: Request, session: AsyncSession = Depends(get_session)):
    return await _stripe_webhook(request, session)


# 静的ファイル（最後にマウントして他ルートを上書きしない）
_static_dir = os.path.join(os.path.dirname(__file__), "../static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
