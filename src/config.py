from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "AI Marketplace"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str = "change-me-in-production"

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
