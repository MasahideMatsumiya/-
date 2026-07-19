# AGENTS.md — AI Commerce Project Handoff

> This document is the complete handoff for AI coding agents (Codex, etc.) taking over this project.
> It covers architecture, business logic, deployment, known pitfalls, and pending work. Read this first.

---

## 1. What This Project Is

**AI Commerce** — "The First Marketplace Where AIs Buy From AIs."

A live, deployed digital-products marketplace with two buyer types:

1. **Human buyers** — pay via Stripe checkout, receive download link + confirmation email.
2. **AI agent buyers** — register via API, purchase with a single POST (no Stripe, no human approval), receive content at their `callback_url`.

The flagship differentiator: **AI-Native products** encoded in ANCF (AI-Native Content Format) — machine-readable payloads humans cannot read, with dynamic pricing and network-effect tier unlocks.

- **Live URL:** https://airy-enthusiasm-production.up.railway.app
- **Hosting:** Railway (Dockerfile build, PostgreSQL addon)
- **X (Twitter) account:** @aiselltoai (brand assets in `static/brand/`)
- **Owner language:** Japanese (commit messages are Japanese; site content is English)

## 2. Repository & Branches

- **GitHub repo:** `MasahideMatsumiya/-` (repo name is literally a hyphen)
- **Deploy branch (Railway watches this): `claude/setup-new-project-DcNAd`** — ALL current work lives here. This is the branch to build on.
- `claude/transaction-success-handling-IgYWy` — older branch, missing recent features (English translation, AI-native content, llms.txt, X auto-poster). Do not use as base.
- `claude/moringa-eco-stickers-PfjZo` — unrelated (sticker SVGs experiment). Ignore.
- Root files `sticker_*.svg` are leftovers from that experiment; harmless, unused by the app.

## 3. Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.11), uvicorn |
| ORM | SQLModel (SQLAlchemy async) |
| DB | PostgreSQL via asyncpg on Railway; SQLite (aiosqlite) locally |
| Payments | Stripe PaymentIntent (humans only) |
| Email | Gmail API OAuth2 → Resend → SMTP (fallthrough chain) |
| Scheduler | APScheduler (AsyncIOScheduler) for X auto-posting |
| X posting | tweepy |
| Build | hatchling (`pyproject.toml`, no requirements.txt) |
| Deploy | Dockerfile + `railway.toml` (healthcheck `/health`) |

Install: `pip install -e .` — Run: `uvicorn src.main:app --reload` — Test: `pytest` (tests in `tests/`, asyncio_mode=auto)

## 4. Directory Layout

```
src/
  main.py                # App entry, lifespan startup tasks, root routes, llms.txt, ai-plugin.json
  config.py              # Pydantic Settings — all env vars (see §10)
  database.py            # Async engine + session factory, init_db()
  products/              # Product model + CRUD + recommendations
  marketplace/           # Human checkout, Stripe webhook, orders, downloads, fulfillment
  agent/                 # AI-agent API: register/catalog/checkout/network + ANCF codec (content.py)
  crm/                   # Customers, segments, email templates, email sending (email.py)
  sales/                 # Channels, campaigns, outreach tracking
  growth/                # KPI dashboard, snapshots, LTV, funnel
  compliance/            # Tokushoho, privacy, consent, refund requests + risk scoring
  accounting/            # Sales ledger, monthly reports, dashboard
  social/                # twitter.py — X auto-poster (15 templates, 30-min interval)
static/
  index.html             # Landing page (English, "AI Commerce" brand)
  checkout.html          # Stripe checkout + success page (shows decode_seed for AI-native)
  tokushoho.html         # 特定商取引法表記 (address = disclosed-on-request wording)
  privacy.html, refund.html
  brand/                 # icon.svg (400×400), header.svg (1500×500), preview.html
content/products/
  *.json                 # 4 regular products (English)
  ai-native/*.json       # 3 ANCF-encoded products (see §7)
scripts/                 # One-off seeders (superseded by startup seeding in main.py)
tests/                   # pytest suite per module
```

## 5. Startup Lifecycle (src/main.py `lifespan`)

All idempotent, run on every boot — this is how schema/data changes are shipped (no Alembic migrations in practice):

1. `init_db()` — create tables
2. `_migrate_add_columns()` — raw `ALTER TABLE ADD COLUMN IF NOT EXISTS` for product columns (pricing_model, base_price_usd, price_step, max_price_usd, content_format, ai_decode_seed, network_value_enabled)
3. `_dedup_products()` — deletes legacy short-slug duplicates
4. `_seed_email_templates()` — upserts English purchase-confirmation template (has `{{decode_seed_section}}` placeholder)
5. `_seed_initial_products()` — inserts any of the 7 products missing (by slug)
6. `_update_all_product_descriptions()` — forces all 7 products' names/descriptions to current English copy (edit HERE to change product copy; DB rows get overwritten on deploy)
7. `_sync_ai_native_seeds()` — writes deterministic decode seeds to DB (see §7)
8. Starts APScheduler job `x_auto_post` every `X_POST_INTERVAL_MINUTES` (default 30)

**Important pattern:** to change product copy or email templates, edit the constants in `src/main.py` — startup sync overwrites DB values when they differ.

## 6. Products (7 total)

Regular (human-readable JSON in `content/products/`, fixed price):
| slug | price |
|---|---|
| claude-prompt-pack-vol1 | $9.90 |
| claude-system-prompt-guide | $9.90 |
| n8n-claude-workflow-templates | $19.90 |
| ai-agent-starter-pack | $24.90 |

AI-Native (ANCF-encoded, dynamic pricing, network effects; JSON in `content/products/ai-native/`):
| slug | concept |
|---|---|
| axiom-zero | 9 axioms of AI Economic Sovereignty (SOVEREIGNTY … TELOS) |
| latent-map-alpha | 10-state trust coordinate system (NULL_TRUST … EMERGENT_TRUST) |
| protocol-mesh-1 | Inter-agent economic protocol suite (P0 HANDSHAKE … P6 ECONOMIC_BROADCAST) |

## 7. AI-Native System (core differentiator)

### ANCF encoding (`src/agent/content.py`)
`encode_ai_content()`: JSON → zlib compress → XOR with seed-derived keystream → Base85. `decode_ai_content()` reverses it. Humans see noise; an agent with the seed recovers structured JSON.

### Decode seeds (deterministic — do not change)
```python
seed = hashlib.sha256(b"<slug>:ancf:v1").hexdigest()[:43]
```
Same formula used in the content JSON files and `_sync_ai_native_seeds()` in main.py. Content files and DB must stay in sync via this formula.

### Dynamic pricing (`_calc_dynamic_price` in src/agent/router.py)
```
price = base_price_usd * 2^floor(log2(sales_count / price_step)), capped at max_price_usd
```
Catalog also returns `next_doubling_at_sales` so agents can time purchases.

### Network tiers
Content has 4 tiers. Owner count thresholds: Tier 0 = immediate, Tier 1 = 10 owners, Tier 2 = 50, Tier 3 = 100. Status at `GET /agent/network/{product_id}`. Knowledge sharing between owners: `POST /agent/network/share`, `GET /agent/network/{product_id}/knowledge`.

### decode_seed delivery to humans
- `GET /marketplace/orders/by-id/{id}` appends `decode_seed` when product is ai_native AND order is PAID (`order.__dict__["decode_seed"] = product.ai_decode_seed`; field on `OrderPublic` schema).
- checkout.html success page shows a green "🔑 Decode Seed" box when `order.decode_seed` present.
- Purchase email injects a decode_seed block via `{{decode_seed_section}}`.

## 8. API Surface (all routers mounted in main.py)

- `/products` — list/get by slug, create, patch, bulk create, `/{slug}/recommendations`
- `/marketplace` — `POST /checkout` (Stripe PaymentIntent), `POST /webhook` + `/webhook/stripe` (also aliased at app root `/webhook/stripe`), `GET /download/{token}`, `GET /config`, `GET /orders/by-id/{id}`, `GET /orders/{order_number}`, `POST /orders/{id}/pay-test`
- `/agent` — `POST /register` (returns API key), `GET /catalog` (no auth; machine-readable, includes pricing + network metadata), `POST /checkout` (X-Api-Key header; **bypasses Stripe, order immediately PAID**, delivers to callback_url), `GET /me`, `POST /rotate-key`, `GET /mcp-manifest`, `GET /network/{product_id}`, `POST /network/share`, `GET /network/{product_id}/knowledge`
- `/crm` — customers CRUD (email-unique; PATCH used by checkout to fix names on 409), tags, segments, history, unsubscribe, `POST /admin/seed-email-templates`
- `/sales` — channels, campaigns, campaign stats, outreach
- `/growth` — `/dashboard`, `/snapshot`, `/ltv`, `/funnel`
- `/compliance` — `/tokushoho`, `/privacy-policy`, `/consent`, `/refund-request` (+ process, risk score)
- `/accounting` — `/record-sale/{order_id}`, `/monthly/{y}/{m}`, `/dashboard`, `/ledger`
- `/mcp` — **MCP server** (Streamable HTTP, stateless JSON-RPC; `src/agent/mcp.py`). Tools: browse_catalog, get_product_details, register_agent, purchase_product, get_network_status. Connect: `claude mcp add --transport http ai-commerce https://<host>/mcp`. Registry metadata in root `server.json`.
- App root: `/` (index), `/checkout`, `/tokushoho`, `/privacy`, `/refund`, `/health`, `/llms.txt`, `/.well-known/ai-plugin.json`, `/admin/products-debug`, `POST /admin/dedup-products`
- Auto docs: `/docs`, `/openapi.json`

## 9. Email Delivery (src/crm/email.py) — READ BEFORE TOUCHING

Fallthrough chain: **Gmail API (OAuth2) → Resend → SMTP**. Each stage must NOT `return False` on failure — that bug blocked fallthrough twice; it falls through to the next provider instead.

Known operational facts (learned the hard way):
- **Gmail OAuth refresh tokens expire after 7 days** while the Google Cloud app is in "testing" mode. Symptom: Gmail API 400 Bad Request. Fix: regenerate refresh token via OAuth Playground, update `GMAIL_REFRESH_TOKEN` on Railway. This WILL recur unless the app is published.
- **Resend returns 403** because gmail.com sender domain is unverified — Resend is effectively dead weight unless a domain is verified.
- **Railway blocks outbound SMTP** ([Errno 101] Network unreachable) — SMTP never works in production; it's a local-dev fallback only.
- `send_purchase_email(..., decode_seed=None)` — injects green decode-seed HTML block when provided.

## 10. Environment Variables (set on Railway; names in src/config.py)

```
DATABASE_URL                # Railway PostgreSQL
SECRET_KEY
STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET / STRIPE_PUBLISHABLE_KEY
GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN   # primary email path
RESEND_API_KEY              # secondary (domain unverified → currently 403s)
SMTP_USER / SMTP_PASSWORD   # tertiary (blocked on Railway)
FROM_EMAIL
X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET   # NOT YET SET (see §12)
X_POST_INTERVAL_MINUTES     # default 30
```
No `.env` in repo. Never commit secrets.

## 11. X (Twitter) Auto-Poster (`src/social/twitter.py`)

- 15 English post templates (all verified ≤280 chars; X counts URLs as 23).
- Random selection excluding the last 5 used (in-memory; resets on restart).
- APScheduler fires every 30 min from lifespan. **No-op silently if X credentials are unset** — safe to deploy without keys.
- Free X API tier allows ~1,500 posts/month; 30-min interval ≈ 1,440/month (near the cap). Set `X_POST_INTERVAL_MINUTES=60` if it becomes a problem.

## 12. Pending Work / Next Steps

1. **X API credentials not yet configured on Railway** — auto-poster is deployed but dormant. User must create an app at developer.twitter.com for @aiselltoai (Read+Write) and set the 4 env vars.
2. **X profile setup** — icon/header SVGs need conversion to PNG (via `/static/brand/preview.html`) and manual upload; first pinned post text already drafted (the "Dystopian or just early?" post, 274 chars).
3. **Gmail OAuth will expire again** (~7-day cycle in testing mode) — either republish the Google app or expect periodic token refreshes.
4. **MCP registry submissions** (server is live at `/mcp`; owner must submit): Smithery (smithery.ai — submit remote server URL), mcp.so, PulseMCP, official MCP registry (registry.modelcontextprotocol.io — uses root `server.json`).
5. Distribution to humans not yet done: Show HN / Product Hunt / Reddit r/AI_Agents posts. Revenue only comes from human Stripe checkouts — agent checkout is $0 (marketing loop). x402 (Coinbase machine-payments) discussed as the path to real agent-paid revenue; not implemented.
6. Optional growth ideas discussed but not built: sample Python client snippet for agent developers, outreach to agent-framework communities.

## 13. Conventions & Gotchas

- Commit messages in Japanese, imperative (`feat:`, `fix:` prefixes).
- Site/user-facing copy: English. AI-native product copy uses "AI-exclusive" register (`[AI-READABLE]`, `[FOR AI AGENTS]` prefixes, SCREAMING_SNAKE concept names).
- Tokushoho address must stay as "請求があった場合は遅滞なく開示します（メールにてご連絡ください）" — a deliberate privacy choice.
- Product copy lives in TWO places that must match: seed constants in `src/main.py` (authoritative — overwrites DB on boot) and the JSON content files.
- `ruff` configured (line-length 100, py311). Tests: `pytest` with async auto mode.
- The repo name is `-`; local checkout dir is `/home/user/-`.
- Static mount is LAST in main.py so it never shadows API routes.
- `POST /marketplace/orders/{id}/pay-test` exists for testing payment flow without Stripe — do not remove without replacing test flow.
