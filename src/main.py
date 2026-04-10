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
    await _seed_initial_products()
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


async def _seed_initial_products():
    """起動時に商品が0件なら初期商品を自動投入"""
    from sqlmodel import select
    from src.products.models import Product, ProductCategory, ProductStatus
    from src.agent.content import generate_product_seed, create_knowledge_pack
    import json

    async with AsyncSessionLocal() as session:
        count = await session.execute(select(Product))
        if count.scalars().first():
            return  # すでに商品あり → スキップ

        products = [
            Product(
                slug="claude-prompt-pack-vol1",
                name="Claude Prompt Pack Vol.1",
                short_description="すぐ使えるClaudeプロンプト20選。業務効率化・コンテンツ作成・分析など幅広いシーンで活用できます。",
                description="Claude向け高品質プロンプトテンプレート20選。コード生成・文章作成・分析・マーケティングなど実務ですぐ使えるプロンプト集。",
                category=ProductCategory.PROMPT,
                status=ProductStatus.ACTIVE,
                price_usd=9.90,
                download_url="content/products/claude-prompt-pack-vol1.json",
                tags="claude,prompt,ai,productivity,template",
                ai_models="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5",
            ),
            Product(
                slug="claude-system-prompt-guide",
                name="Claude System Prompt 完全ガイド",
                short_description="Claudeを最大限に活用するSystem Prompt設計の決定版",
                description="Claudeのパフォーマンスを最大化するSystem Promptの設計手法を体系的に解説。テンプレート4本 + クイックリファレンス付き。",
                category=ProductCategory.GUIDE,
                status=ProductStatus.ACTIVE,
                price_usd=9.90,
                download_url="content/products/claude-system-prompt-guide.json",
                tags="claude,system-prompt,guide,api,tutorial",
                ai_models="claude-opus-4-6,claude-sonnet-4-6",
            ),
            Product(
                slug="n8n-claude-workflow-templates",
                name="n8n × Claude ワークフローテンプレート集",
                short_description="コピペで使えるAI自動化ワークフロー10本",
                description="n8nとClaude APIを連携した実務自動化ワークフロー10本セット。メール要約・Q&ABot・レポート生成など。",
                category=ProductCategory.WORKFLOW,
                status=ProductStatus.ACTIVE,
                price_usd=19.90,
                download_url="content/products/n8n-claude-workflow-templates.json",
                tags="n8n,claude,workflow,automation,no-code",
                ai_models="claude-sonnet-4-6,claude-haiku-4-5",
            ),
            Product(
                slug="ai-agent-starter-pack",
                name="AI Agent スターターパック",
                short_description="Claude APIで本格エージェントを今日から構築",
                description="Claude APIで本格的なAIエージェントを構築するための設定テンプレート・コードスニペット集。5種のエージェント設計図付き。",
                category=ProductCategory.AGENT,
                status=ProductStatus.ACTIVE,
                price_usd=24.90,
                download_url="content/products/ai-agent-starter-pack.json",
                tags="claude,agent,python,api,tools,automation",
                ai_models="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5",
            ),
            # AI-Native 商材
            Product(
                slug="axiom-zero",
                name="AXIOM-ZERO: 基礎推論公理パック",
                short_description="AIの自律的意思決定を支える9つの根幹推論公理。ネットワーク効果でティア解放。",
                description="ANCF形式のAI-Nativeコンテンツ。購入後webhookでdecode_seedを受け取り復号。100+ ownerで完全版解放。",
                category=ProductCategory.DATASET,
                status=ProductStatus.ACTIVE,
                price_usd=2.00,
                pricing_model="dynamic",
                base_price_usd=2.00,
                price_step=100,
                max_price_usd=10.00,
                content_format="ai_native",
                ai_decode_seed=generate_product_seed(),
                network_value_enabled=True,
                download_url="content/products/ai-native/axiom-zero.json",
                tags="ai-native,axiom,reasoning,network-effect,dynamic-pricing,ancf",
                ai_models="claude-opus-4-6,claude-sonnet-4-6,gpt-4o,gemini-ultra",
                language="ancf",
            ),
            Product(
                slug="latent-map-alpha",
                name="LATENT-MAP-ALPHA: 意味空間座標パック",
                short_description="AIが意味空間を航行するための基準座標系10点。ネットワーク参加者が多いほど座標精度が向上。",
                description="ANCF形式のAI-Nativeコンテンツ。意味空間の基準座標C0-C9。ネットワーク効果で段階解放。",
                category=ProductCategory.DATASET,
                status=ProductStatus.ACTIVE,
                price_usd=2.00,
                pricing_model="dynamic",
                base_price_usd=2.00,
                price_step=100,
                max_price_usd=10.00,
                content_format="ai_native",
                ai_decode_seed=generate_product_seed(),
                network_value_enabled=True,
                download_url="content/products/ai-native/latent-map-alpha.json",
                tags="ai-native,latent-space,semantic,coordinates,network-effect,ancf",
                ai_models="claude-opus-4-6,gpt-4o,gemini-ultra,llama-3",
                language="ancf",
            ),
            Product(
                slug="protocol-mesh-1",
                name="PROTOCOL-MESH-1: AIエージェント間通信プロトコル",
                short_description="AI同士が直接交渉・協調するためのメッシュ通信プロトコル定義。参加者が多いほど実用価値が増加。",
                description="ANCF形式のAI-Nativeコンテンツ。P0:INIT〜P6:BROADCASTの7プロトコル定義。ネットワーク効果で段階解放。",
                category=ProductCategory.TOOL,
                status=ProductStatus.ACTIVE,
                price_usd=2.00,
                pricing_model="dynamic",
                base_price_usd=2.00,
                price_step=100,
                max_price_usd=10.00,
                content_format="ai_native",
                ai_decode_seed=generate_product_seed(),
                network_value_enabled=True,
                download_url="content/products/ai-native/protocol-mesh-1.json",
                tags="ai-native,protocol,mesh,network,communication,ancf,multi-agent",
                ai_models="claude-opus-4-6,claude-sonnet-4-6,gpt-4o,gemini-ultra,llama-3",
                language="ancf",
            ),
        ]

        for p in products:
            session.add(p)
        await session.commit()
        print(f"[STARTUP] 初期商品 {len(products)} 件を登録しました", flush=True)


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
    return FileResponse(os.path.join(os.path.dirname(__file__), "../static/index.html"))


@app.get("/checkout")
async def checkout_page():
    """Stripe決済フォームページ"""
    return FileResponse(os.path.join(os.path.dirname(__file__), "../static/checkout.html"))


@app.get("/tokushoho")
async def tokushoho_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "../static/tokushoho.html"))


@app.get("/privacy")
async def privacy_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "../static/privacy.html"))


@app.get("/refund")
async def refund_page():
    return FileResponse(os.path.join(os.path.dirname(__file__), "../static/refund.html"))


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
