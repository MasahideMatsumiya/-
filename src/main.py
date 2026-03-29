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
from src.database import AsyncSessionLocal, get_session, init_db
from src.growth.router import router as growth_router
from src.marketplace.router import router as marketplace_router, stripe_webhook as _stripe_webhook
from src.products.router import router as products_router
from src.sales.router import router as sales_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_email_templates()
    yield


async def _seed_email_templates():
    """起動時に購入確認メールテンプレートを自動登録"""
    from sqlmodel import select
    from src.crm.models import EmailTemplate
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(EmailTemplate).where(EmailTemplate.trigger == "purchase")
        )
        if existing.scalar_one_or_none():
            return
        session.add(EmailTemplate(
            name="購入確認メール",
            trigger="purchase",
            subject="【AI Marketplace】ご購入ありがとうございます - {{order_number}}",
            body_html="""<h2>{{name}} 様、ご購入ありがとうございます！</h2>
<p>商品: <strong>{{product_name}}</strong></p>
<p>注文番号: {{order_number}}</p>
<p><a href="{{download_url}}" style="background:#0070f3;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">ダウンロードする</a></p>
<p>ダウンロードリンクは30日間有効です。</p>""",
            body_text="{{name}} 様、ご購入ありがとうございます！\n商品: {{product_name}}\n注文番号: {{order_number}}\nダウンロード: {{download_url}}",
        ))
        await session.commit()
        print("[STARTUP] 購入確認メールテンプレートを登録しました", flush=True)


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
