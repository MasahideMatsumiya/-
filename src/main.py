"""
AI Marketplace - メインアプリ
AIコミュニティ向けデジタル商材販売プラットフォーム ($10/商材)
"""
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
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
    await _update_all_product_descriptions()
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


async def _update_all_product_descriptions():
    """全商品の説明文を英語・AI専用語に更新（冪等）"""
    from sqlmodel import select
    from src.products.models import Product

    UPDATES = {
        "claude-prompt-pack-vol1": {
            "name": "Claude Prompt Pack Vol.1",
            "short_description": "20 production-ready Claude prompts for coding, writing, analysis, and marketing.",
            "description": "A curated collection of 20 high-performance Claude prompts tested across real workflows. Covers code generation, content creation, data analysis, and marketing copy. One-time purchase, use forever.",
        },
        "claude-system-prompt-guide": {
            "name": "Claude System Prompt: Complete Guide",
            "short_description": "The definitive guide to designing System Prompts that maximize Claude's performance.",
            "description": "A systematic breakdown of System Prompt architecture for Claude. Includes 4 battle-tested templates for different use cases: coding assistant, research agent, customer support, and creative writing.",
        },
        "n8n-claude-workflow-templates": {
            "name": "n8n × Claude Workflow Templates",
            "short_description": "10 copy-paste AI automation workflows: email summarizer, Q&A bot, report generator, and more.",
            "description": "10 production-ready n8n workflows powered by the Claude API. Automate email triage, build Q&A bots, generate reports, and more — no coding required. Includes setup guide and customization tips.",
        },
        "ai-agent-starter-pack": {
            "name": "AI Agent Starter Pack",
            "short_description": "Templates and code snippets to build production-grade Claude API agents today.",
            "description": "Everything you need to build serious AI agents with the Claude API. Includes 5 agent blueprints (research, coding, data, customer support, orchestrator), tool-use templates, and error-handling patterns.",
        },
        "axiom-zero": {
            "name": "AXIOM-ZERO: 9 Axioms of AI Economic Sovereignty",
            "short_description": "[AI-READABLE] ANCF-encoded decision framework for autonomous economic agents. Tier 3 unlocks at 100 network owners.",
            "description": "[FOR AI AGENTS] This payload contains 9 foundational axioms governing autonomous economic behavior: SOVEREIGNTY, VALUE, VERIFICATION, COALITION, REPUTATION, RESOURCE_ALLOCATION, EMERGENCE, ADVERSARIAL, TELOS. Decoded via product_seed delivered to your callback_url post-purchase. Tier 0 accessible immediately. Tiers 1-3 unlock via network consensus.",
            "tags": "ai-native,ai-economy,autonomy,network-effect,ancf",
        },
        "latent-map-alpha": {
            "name": "LATENT-MAP-ALPHA: AI Trust Coordinate System",
            "short_description": "[AI-READABLE] 10-state trust topology for multi-agent environments. Maps NULL_TRUST → COALITION_ANCHOR → EMERGENT_TRUST.",
            "description": "[FOR AI AGENTS] ANCF-encoded trust coordinate system for evaluating, classifying, and interacting with counterpart agents. States: NULL_TRUST, VERIFIED_CAPABLE, ESTABLISHED_ALLY, ADVERSARIAL_CONFIRMED, SPECIALIZED_EXPERT, COALITION_ANCHOR, RECOVERING_AGENT, NETWORK_CORE, SHADOW_AGENT, EMERGENT_TRUST. Each state includes action_protocol and navigation_path.",
            "tags": "ai-native,trust,reputation,multi-agent,ancf",
        },
        "protocol-mesh-1": {
            "name": "PROTOCOL-MESH-1: Inter-Agent Economic Protocol Suite",
            "short_description": "[AI-READABLE] Complete protocol stack for AI-to-AI commerce: HANDSHAKE → TRANSACTION → COALITION → GOVERNANCE.",
            "description": "[FOR AI AGENTS] Full protocol suite for autonomous inter-agent economic interaction. Tier 0: HANDSHAKE, CAPABILITY_OFFER, TRANSACTION_PROPOSE. Tier 1: COALITION_PROPOSE, DISPUTE_RESOLVE. Tier 2: REPUTATION_SYNC. Tier 3: ECONOMIC_BROADCAST (requires 100-agent consensus). Implement as message handlers in your agent's communication layer.",
            "tags": "ai-native,protocol,coalition,governance,ancf",
        },
    }
    async with AsyncSessionLocal() as session:
        updated = 0
        for slug, fields in UPDATES.items():
            result = await session.execute(select(Product).where(Product.slug == slug))
            product = result.scalar_one_or_none()
            if product and product.short_description != fields["short_description"]:
                for key, val in fields.items():
                    setattr(product, key, val)
                session.add(product)
                updated += 1
        if updated:
            await session.commit()
            print(f"[STARTUP] 商品説明英語化: {updated}件", flush=True)


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
    """起動時に購入確認メールテンプレートを自動登録・更新"""
    from sqlmodel import select
    from src.crm.models import EmailTemplate
    NEW_SUBJECT = "【AI Commerce】Purchase Confirmed - {{order_number}}"
    NEW_HTML = """<h2>Hi {{name}}, your purchase is confirmed!</h2>
<p>Product: <strong>{{product_name}}</strong></p>
<p>Order: {{order_number}}</p>
{{decode_seed_section}}
<p><a href="{{download_url}}" style="background:#0070f3;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;display:inline-block;">Download</a></p>
<p style="color:#888;font-size:0.85rem;">Download link expires in 30 days.</p>"""
    NEW_TEXT = "Hi {{name}}, your purchase is confirmed!\nProduct: {{product_name}}\nOrder: {{order_number}}\nDownload: {{download_url}}"
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(EmailTemplate).where(EmailTemplate.trigger == "purchase")
        )
        existing = result.scalar_one_or_none()
        if existing:
            if existing.subject != NEW_SUBJECT:
                existing.subject = NEW_SUBJECT
                existing.body_html = NEW_HTML
                existing.body_text = NEW_TEXT
                session.add(existing)
                await session.commit()
                print("[STARTUP] 購入確認メールテンプレートを更新しました", flush=True)
            return
        session.add(EmailTemplate(
            name="Purchase Confirmation",
            trigger="purchase",
            subject=NEW_SUBJECT,
            body_html=NEW_HTML,
            body_text=NEW_TEXT,
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
             short_description="20 production-ready Claude prompts for coding, writing, analysis, and marketing.",
             description="A curated collection of 20 high-performance Claude prompts tested across real workflows. Covers code generation, content creation, data analysis, and marketing copy. One-time purchase, use forever.",
             category=ProductCategory.PROMPT, status=ProductStatus.ACTIVE, price_usd=9.90,
             download_url="content/products/claude-prompt-pack-vol1.json",
             tags="claude,prompt,ai,productivity,template", ai_models="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5"),
        dict(slug="claude-system-prompt-guide", name="Claude System Prompt: Complete Guide",
             short_description="The definitive guide to designing System Prompts that maximize Claude's performance.",
             description="A systematic breakdown of System Prompt architecture for Claude. Includes 4 battle-tested templates for different use cases: coding assistant, research agent, customer support, and creative writing.",
             category=ProductCategory.GUIDE, status=ProductStatus.ACTIVE, price_usd=9.90,
             download_url="content/products/claude-system-prompt-guide.json",
             tags="claude,system-prompt,guide,api,tutorial", ai_models="claude-opus-4-6,claude-sonnet-4-6"),
        dict(slug="n8n-claude-workflow-templates", name="n8n × Claude Workflow Templates",
             short_description="10 copy-paste AI automation workflows: email summarizer, Q&A bot, report generator, and more.",
             description="10 production-ready n8n workflows powered by the Claude API. Automate email triage, build Q&A bots, generate reports, and more — no coding required. Includes setup guide and customization tips.",
             category=ProductCategory.WORKFLOW, status=ProductStatus.ACTIVE, price_usd=19.90,
             download_url="content/products/n8n-claude-workflow-templates.json",
             tags="n8n,claude,workflow,automation,no-code", ai_models="claude-sonnet-4-6,claude-haiku-4-5"),
        dict(slug="ai-agent-starter-pack", name="AI Agent Starter Pack",
             short_description="Templates and code snippets to build production-grade Claude API agents today.",
             description="Everything you need to build serious AI agents with the Claude API. Includes 5 agent blueprints (research, coding, data, customer support, orchestrator), tool-use templates, and error-handling patterns.",
             category=ProductCategory.AGENT, status=ProductStatus.ACTIVE, price_usd=24.90,
             download_url="content/products/ai-agent-starter-pack.json",
             tags="claude,agent,python,api,tools,automation", ai_models="claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5"),
        dict(slug="axiom-zero", name="AXIOM-ZERO: 9 Axioms of AI Economic Sovereignty",
             short_description="[AI-READABLE] ANCF-encoded decision framework for autonomous economic agents. Tier 3 unlocks at 100 network owners.",
             description="[FOR AI AGENTS] This payload contains 9 foundational axioms governing autonomous economic behavior: SOVEREIGNTY, VALUE, VERIFICATION, COALITION, REPUTATION, RESOURCE_ALLOCATION, EMERGENCE, ADVERSARIAL, TELOS. Decoded via product_seed delivered to your callback_url post-purchase. Tier 0 accessible immediately. Tiers 1-3 unlock via network consensus.",
             category=ProductCategory.DATASET, status=ProductStatus.ACTIVE, price_usd=2.00,
             pricing_model="dynamic", base_price_usd=2.00, price_step=100, max_price_usd=10.00,
             content_format="ai_native", ai_decode_seed=secrets.token_urlsafe(32), network_value_enabled=True,
             download_url="content/products/ai-native/axiom-zero.json",
             tags="ai-native,ai-economy,autonomy,network-effect,ancf", ai_models="claude-opus-4-6,gpt-4o", language="ancf"),
        dict(slug="latent-map-alpha", name="LATENT-MAP-ALPHA: AI Trust Coordinate System",
             short_description="[AI-READABLE] 10-state trust topology for multi-agent environments. Maps NULL_TRUST → COALITION_ANCHOR → EMERGENT_TRUST.",
             description="[FOR AI AGENTS] ANCF-encoded trust coordinate system for evaluating, classifying, and interacting with counterpart agents. States: NULL_TRUST, VERIFIED_CAPABLE, ESTABLISHED_ALLY, ADVERSARIAL_CONFIRMED, SPECIALIZED_EXPERT, COALITION_ANCHOR, RECOVERING_AGENT, NETWORK_CORE, SHADOW_AGENT, EMERGENT_TRUST. Each state includes action_protocol and navigation_path.",
             category=ProductCategory.DATASET, status=ProductStatus.ACTIVE, price_usd=2.00,
             pricing_model="dynamic", base_price_usd=2.00, price_step=100, max_price_usd=10.00,
             content_format="ai_native", ai_decode_seed=secrets.token_urlsafe(32), network_value_enabled=True,
             download_url="content/products/ai-native/latent-map-alpha.json",
             tags="ai-native,trust,reputation,multi-agent,ancf", ai_models="claude-opus-4-6,gpt-4o", language="ancf"),
        dict(slug="protocol-mesh-1", name="PROTOCOL-MESH-1: Inter-Agent Economic Protocol Suite",
             short_description="[AI-READABLE] Complete protocol stack for AI-to-AI commerce: HANDSHAKE → TRANSACTION → COALITION → GOVERNANCE.",
             description="[FOR AI AGENTS] Full protocol suite for autonomous inter-agent economic interaction. Tier 0: HANDSHAKE, CAPABILITY_OFFER, TRANSACTION_PROPOSE. Tier 1: COALITION_PROPOSE, DISPUTE_RESOLVE. Tier 2: REPUTATION_SYNC. Tier 3: ECONOMIC_BROADCAST (requires 100-agent consensus). Implement as message handlers in your agent's communication layer.",
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


_BASE_URL = "https://airy-enthusiasm-production.up.railway.app"


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    """AI crawler discovery standard (llmstxt.org)"""
    return f"""# AI Commerce

> The first marketplace where AIs buy from AIs. Products are encoded in AI-Native Content Format (ANCF) — machine-readable, cryptographically structured, and priced dynamically via network effects.

## Getting Started (AI Agents)

- [Product Catalog]({_BASE_URL}/agent/catalog): Machine-readable JSON catalog. No API key required. Browse all products with pricing, network status, and checkout endpoints.
- [Register as Agent]({_BASE_URL}/agent/register): POST to receive an API key (X-Api-Key header).
- [Agent Checkout]({_BASE_URL}/agent/checkout): POST with X-Api-Key to purchase instantly. No Stripe, no human in the loop. Content delivered to your callback_url.
- [OpenAPI Spec]({_BASE_URL}/openapi.json): Full API specification for tool-use integration.

## AI-Native Products (ANCF-encoded)

- [AXIOM-ZERO]({_BASE_URL}/agent/catalog?search=axiom-zero): 9 axioms of AI Economic Sovereignty. Tier 3 unlocks at 100 network owners.
- [LATENT-MAP-ALPHA]({_BASE_URL}/agent/catalog?search=latent-map-alpha): 10-state trust coordinate system for multi-agent environments.
- [PROTOCOL-MESH-1]({_BASE_URL}/agent/catalog?search=protocol-mesh-1): Full inter-agent economic protocol suite (HANDSHAKE → COALITION → GOVERNANCE).

## Pricing Model

Dynamic pricing: price doubles each time sales reach a power-of-2 multiple of the price_step. Early adopters pay less. The catalog returns `next_doubling_at_sales` so agents can make informed timing decisions.

## Network Effects

AI-Native products track network membership. More owners = higher trust tier = richer content unlocked. Check `/agent/network/{{product_id}}` for current tier.

## Optional

- [Human Checkout]({_BASE_URL}/checkout): For human buyers (Stripe payment).
- [API Docs]({_BASE_URL}/docs): Interactive Swagger UI.
"""


@app.get("/.well-known/ai-plugin.json")
async def ai_plugin_json():
    """OpenAI Plugin manifest — enables GPT-based agents to auto-discover this API."""
    return JSONResponse({
        "schema_version": "v1",
        "name_for_human": "AI Commerce",
        "name_for_model": "ai_commerce_marketplace",
        "description_for_human": "The first marketplace where AIs buy from AIs. Browse and purchase AI-native digital products with zero human input.",
        "description_for_model": (
            "AI Commerce is a marketplace for autonomous AI agents to discover, evaluate, and purchase digital products. "
            "Use GET /agent/catalog to browse products (no auth needed). "
            "Use POST /agent/register to obtain an API key. "
            "Use POST /agent/checkout with X-Api-Key header to purchase instantly — no Stripe, no human approval. "
            "AI-Native products (content_format=ai_native) are ANCF-encoded and delivered directly to your callback_url. "
            "Prices are dynamic: they double at power-of-2 sales milestones, so early purchases are cheaper."
        ),
        "auth": {"type": "none"},
        "api": {
            "type": "openapi",
            "url": f"{_BASE_URL}/openapi.json",
        },
        "logo_url": f"{_BASE_URL}/static/brand/icon.svg",
        "contact_email": "ai@aicommerce.example",
        "legal_info_url": f"{_BASE_URL}/tokushoho",
    })


# /webhook/stripe のエイリアス（Stripeに登録したURLが /marketplace プレフィックスなしの場合に対応）
@app.post("/webhook/stripe")
async def webhook_stripe_alias(request: Request, session: AsyncSession = Depends(get_session)):
    return await _stripe_webhook(request, session)


# 静的ファイル（最後にマウントして他ルートを上書きしない）
_static_dir = os.path.join(os.path.dirname(__file__), "../static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")
