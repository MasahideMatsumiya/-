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
    await _migrate_add_columns()
    await _dedup_products()
    await _seed_email_templates()
    await _seed_initial_products()
    await _sync_ai_native_seeds()
    yield


async def _dedup_products():
    """古い短スラッグ商品を削除（正しいスラッグ版が存在する場合のみ）"""
    from sqlmodel import select
    from src.products.models import Product
    # 正しいスラッグと古い短スラッグのペア
    REPLACE_SLUGS = {
        "claude-system-prompt": "claude-system-prompt-guide",
        "n8n-claude": "n8n-claude-workflow-templates",
        "ai-agent": "ai-agent-starter-pack",
    }
    async with AsyncSessionLocal() as session:
        deleted = 0
        for old_slug, new_slug in REPLACE_SLUGS.items():
            # 正しい版が存在する場合のみ古い版を削除
            new_exists = await session.execute(select(Product).where(Product.slug == new_slug))
            if not new_exists.scalar_one_or_none():
                continue
            old = await session.execute(select(Product).where(Product.slug == old_slug))
            old_product = old.scalar_one_or_none()
            if old_product:
                await session.delete(old_product)
                deleted += 1
        if deleted:
            await session.commit()
            print(f"[STARTUP] 旧スラッグ商品 {deleted} 件を削除しました", flush=True)


async def _migrate_add_columns():
    """既存テーブルに不足カラムを追加（冪等）"""
    from src.database import engine
    async with engine.begin() as conn:
        migrations = [
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS pricing_model VARCHAR DEFAULT 'fixed'",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS base_price_usd FLOAT",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS price_step INTEGER DEFAULT 100",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS max_price_usd FLOAT",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS content_format VARCHAR DEFAULT 'human'",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS ai_decode_seed VARCHAR",
            "ALTER TABLE product ADD COLUMN IF NOT EXISTS network_value_enabled BOOLEAN DEFAULT FALSE",
        ]
        for sql in migrations:
            try:
                await conn.execute(__import__("sqlalchemy").text(sql))
            except Exception:
                pass  # SQLite等でIF NOT EXISTSが使えない場合は無視
    print("[STARTUP] マイグレーション完了", flush=True)


async def _sync_ai_native_seeds():
    """AI-Nativeコンテンツファイルと同じシードをDBに設定（冪等）"""
    import hashlib
    from sqlmodel import select
    from src.products.models import Product

    SEEDS = {
        "axiom-zero":       hashlib.sha256(b"axiom-zero:ancf:v1").hexdigest()[:43],
        "latent-map-alpha": hashlib.sha256(b"latent-map-alpha:ancf:v1").hexdigest()[:43],
        "protocol-mesh-1":  hashlib.sha256(b"protocol-mesh-1:ancf:v1").hexdigest()[:43],
    }
    async with AsyncSessionLocal() as session:
        updated = 0
        for slug, seed in SEEDS.items():
            result = await session.execute(select(Product).where(Product.slug == slug))
            product = result.scalar_one_or_none()
            if product and product.ai_decode_seed != seed:
                product.ai_decode_seed = seed
                session.add(product)
                updated += 1
        if updated:
            await session.commit()
            print(f"[STARTUP] AI-Nativeシード同期: {updated}件", flush=True)


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
    """起動時にスラッグごとに存在確認し、不足商品だけ追加"""
    import secrets
    from sqlmodel import select
    from src.products.models import Product, ProductCategory, ProductStatus

    SEED_PRODUCTS = [
        dict(slug="claude-prompt-pack-vol1", name="Claude Prompt Pack Vol.1",
             short_description="すぐ使えるClaudeプロンプト20選。業務効率化・コンテンツ作成・分析など幅広いシーンで活用できます。",
             description="Claude向け高品質プロンプトテンプレート20選。コード生成・文章作成・分析・マーケティングなど実務ですぐ使えるプロンプト集。",
             category=ProductCategory.PROMPT, status=ProductStatus.ACTIVE, price_usd=9.90,
             download_url="content/products/claude-prompt-pack-vol1.json",
             tags="claude,prompt,ai,productivity,template", ai_models="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5"),
        dict(slug="claude-system-prompt-guide", name="Claude System Prompt 完全ガイド",
             short_description="Claudeを最大限に活用するSystem Prompt設計の決定版",
             description="Claudeのパフォーマンスを最大化するSystem Promptの設計手法を体系的に解説。テンプレート4本付き。",
             category=ProductCategory.GUIDE, status=ProductStatus.ACTIVE, price_usd=9.90,
             download_url="content/products/claude-system-prompt-guide.json",
             tags="claude,system-prompt,guide,api,tutorial", ai_models="claude-opus-4-6,claude-sonnet-4-6"),
        dict(slug="n8n-claude-workflow-templates", name="n8n × Claude ワークフローテンプレート集",
             short_description="コピペで使えるAI自動化ワークフロー10本",
             description="n8nとClaude APIを連携した実務自動化ワークフロー10本セット。メール要約・Q&ABot・レポート生成など。",
             category=ProductCategory.WORKFLOW, status=ProductStatus.ACTIVE, price_usd=19.90,
             download_url="content/products/n8n-claude-workflow-templates.json",
             tags="n8n,claude,workflow,automation,no-code", ai_models="claude-sonnet-4-6,claude-haiku-4-5"),
        dict(slug="ai-agent-starter-pack", name="AI Agent スターターパック",
             short_description="Claude APIで本格エージェントを今日から構築",
             description="Claude APIで本格的なAIエージェントを構築するための設定テンプレート・コードスニペット集。5種のエージェント設計図付き。",
             category=ProductCategory.AGENT, status=ProductStatus.ACTIVE, price_usd=24.90,
             download_url="content/products/ai-agent-starter-pack.json",
             tags="claude,agent,python,api,tools,automation", ai_models="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5"),
        dict(slug="axiom-zero", name="AXIOM-ZERO: 基礎推論公理パック",
             short_description="AIの自律的意思決定を支える9つの根幹推論公理。ネットワーク効果でティア解放。",
             description="ANCF形式のAI-Nativeコンテンツ。購入後webhookでdecode_seedを受け取り復号。100+ ownerで完全版解放。",
             category=ProductCategory.DATASET, status=ProductStatus.ACTIVE, price_usd=2.00,
             pricing_model="dynamic", base_price_usd=2.00, price_step=100, max_price_usd=10.00,
             content_format="ai_native", ai_decode_seed=secrets.token_urlsafe(32), network_value_enabled=True,
             download_url="content/products/ai-native/axiom-zero.json",
             tags="ai-native,axiom,reasoning,network-effect,ancf", ai_models="claude-opus-4-6,gpt-4o", language="ancf"),
        dict(slug="latent-map-alpha", name="LATENT-MAP-ALPHA: 意味空間座標パック",
             short_description="AIが意味空間を航行するための基準座標系10点。ネットワーク参加者が多いほど座標精度が向上。",
             description="ANCF形式のAI-Nativeコンテンツ。意味空間の基準座標C0-C9。ネットワーク効果で段階解放。",
             category=ProductCategory.DATASET, status=ProductStatus.ACTIVE, price_usd=2.00,
             pricing_model="dynamic", base_price_usd=2.00, price_step=100, max_price_usd=10.00,
             content_format="ai_native", ai_decode_seed=secrets.token_urlsafe(32), network_value_enabled=True,
             download_url="content/products/ai-native/latent-map-alpha.json",
             tags="ai-native,latent-space,semantic,ancf", ai_models="claude-opus-4-6,gpt-4o", language="ancf"),
        dict(slug="protocol-mesh-1", name="PROTOCOL-MESH-1: AIエージェント間通信プロトコル",
             short_description="AI同士が直接交渉・協調するためのメッシュ通信プロトコル定義。参加者が多いほど実用価値が増加。",
             description="ANCF形式のAI-Nativeコンテンツ。P0:INIT〜P6:BROADCASTの7プロトコル定義。ネットワーク効果で段階解放。",
             category=ProductCategory.TOOL, status=ProductStatus.ACTIVE, price_usd=2.00,
             pricing_model="dynamic", base_price_usd=2.00, price_step=100, max_price_usd=10.00,
             content_format="ai_native", ai_decode_seed=secrets.token_urlsafe(32), network_value_enabled=True,
             download_url="content/products/ai-native/protocol-mesh-1.json",
             tags="ai-native,protocol,mesh,ancf", ai_models="claude-opus-4-6,gpt-4o", language="ancf"),
    ]

    async with AsyncSessionLocal() as session:
        added = 0
        for data in SEED_PRODUCTS:
            exists = await session.execute(select(Product).where(Product.slug == data["slug"]))
            if exists.scalar_one_or_none():
                continue
            session.add(Product(**data))
            added += 1
        if added:
            await session.commit()
            print(f"[STARTUP] 商品 {added} 件を追加しました", flush=True)


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


@app.get("/admin/products-debug")
async def products_debug(session: AsyncSession = Depends(get_session)):
    """全商品のIDとスラッグを返す（デバッグ用）"""
    from sqlmodel import select
    from src.products.models import Product
    result = await session.execute(select(Product).order_by(Product.id))
    products = result.scalars().all()
    return [{"id": p.id, "slug": p.slug, "name": p.name, "status": p.status} for p in products]


@app.post("/admin/dedup-products")
async def dedup_products(session: AsyncSession = Depends(get_session)):
    """重複商品を削除（スラッグごとに最新1件だけ残す）"""
    from sqlmodel import select
    from src.products.models import Product
    result = await session.execute(select(Product).order_by(Product.id))
    products = result.scalars().all()
    seen = {}
    deleted = 0
    for p in products:
        if p.slug in seen:
            await session.delete(p)
            deleted += 1
        else:
            seen[p.slug] = p.id
    await session.commit()
    return {"deleted": deleted, "remaining": len(seen)}


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
