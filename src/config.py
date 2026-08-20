from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "AI Marketplace"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    app_url: str = "https://airy-enthusiasm-production.up.railway.app"

    # Database
    database_url: str = "sqlite+aiosqlite:///./ai_marketplace.db"

    # Stripe ($10 tier products)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = "noreply@ai-marketplace.com"
    resend_api_key: str = ""
    # Gmail API (OAuth2)
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""

    # X (Twitter) API — for auto-posting
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    x_post_interval_minutes: int = 30

    # x402 (machine payments — USDC on Base)
    x402_pay_to_address: str = ""          # 受取ウォレット(Base EVMアドレス)。未設定ならGENESIS販売は準備中扱い
    x402_network: str = "base"             # "base" (mainnet) | "base-sepolia" (testnet)
    x402_facilitator_url: str = "https://x402.org/facilitator"
    x402_max_timeout_seconds: int = 300

    # GENESIS series (100 one-of-one editions, x402-only)
    genesis_total_editions: int = 100
    genesis_base_price_usd: float = 10.0
    genesis_final_price_usd: float = 500.0

    # Business
    platform_fee_percent: float = 10.0  # 10% platform fee
    default_price_usd: float = 10.0
    currency: str = "usd"

    # Tax (consumption tax / 消費税)
    tax_rate_jp: float = 0.10  # Japan 10%
    tax_rate_us: float = 0.0   # US varies by state

    class Config:
        env_file = ".env"


settings = Settings()
