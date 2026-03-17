"""
AI Marketplace - メインアプリ
AIコミュニティ向けデジタル商材販売プラットフォーム ($10/商材)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.accounting.router import router as accounting_router
from src.compliance.router import router as compliance_router
from src.config import settings
from src.crm.router import router as crm_router
from src.database import init_db
from src.growth.router import router as growth_router
from src.marketplace.router import router as marketplace_router
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
        ],
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
