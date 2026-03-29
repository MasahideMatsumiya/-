"""
メール自動送信モジュール
購入確認・フォローアップ・再エンゲージメント・ニュースレター
"""
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.config import settings
from src.crm.models import Customer, EmailLog, EmailTemplate


def _render(template: str, variables: dict) -> str:
    """{{key}} 形式のテンプレート変数を置換"""
    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def _get_gmail_access_token() -> str:
    """Gmail OAuthのrefresh_tokenからaccess_tokenを取得"""
    resp = httpx.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "refresh_token",
        "refresh_token": settings.gmail_refresh_token,
        "client_id": settings.gmail_client_id,
        "client_secret": settings.gmail_client_secret,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _send_gmail_api(to_email: str, subject: str, body_html: str, body_text: str) -> bool:
    """Gmail API（HTTPS）でメール送信"""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user or settings.from_email
    msg["To"] = to_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    access_token = _get_gmail_access_token()
    resp = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=15,
    )
    if resp.status_code == 200:
        print(f"[EMAIL] Gmail API OK → {to_email} subject={subject[:40]}", flush=True)
        return True
    print(f"[EMAIL ERROR] Gmail API {resp.status_code}: {resp.text[:200]}", flush=True)
    return False


def _send_email(to_email: str, subject: str, body_html: str, body_text: str) -> bool:
    """メール送信。Gmail API優先、次にResend、なければSMTP。"""
    # Gmail API（HTTPS経由・Railway対応）
    if settings.gmail_client_id and settings.gmail_refresh_token:
        try:
            return _send_gmail_api(to_email, subject, body_html, body_text)
        except Exception as e:
            print(f"[EMAIL ERROR] Gmail API {type(e).__name__}: {e}", flush=True)
            return False

    # Resend HTTP API
    if settings.resend_api_key:
        try:
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.from_email,
                    "to": [to_email],
                    "subject": subject,
                    "html": body_html,
                    "text": body_text,
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                print(f"[EMAIL] Resend OK → {to_email} subject={subject[:40]}", flush=True)
                return True
            else:
                print(f"[EMAIL ERROR] Resend {resp.status_code}: {resp.text[:200]}", flush=True)
                return False
        except Exception as e:
            print(f"[EMAIL ERROR] Resend {type(e).__name__}: {e}", flush=True)
            return False

    # SMTP フォールバック
    if not settings.smtp_user or not settings.smtp_password:
        print("[EMAIL] スキップ: RESEND_API_KEY も SMTP 設定もありません", flush=True)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.from_email
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.from_email, to_email, msg.as_string())
        print(f"[EMAIL] SMTP OK → {to_email} subject={subject[:40]}", flush=True)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] SMTP {type(e).__name__}: {e}", flush=True)
        return False


async def send_trigger_email(
    customer_id: int,
    trigger: str,
    variables: dict,
    session: AsyncSession,
) -> bool:
    """
    トリガーに対応するテンプレートでメールを送信し、ログを記録する。

    trigger: "welcome" | "purchase" | "followup_3d" | "followup_7d" |
             "reengagement" | "newsletter"
    variables: テンプレート内の {{key}} を置換する dict
    """
    customer = await session.get(Customer, customer_id)
    if not customer or not customer.email_subscribed or customer.fraud_flagged:
        return False

    template_result = await session.execute(
        select(EmailTemplate).where(
            EmailTemplate.trigger == trigger,
            EmailTemplate.is_active,
        )
    )
    template = template_result.scalar_one_or_none()
    if not template:
        return False  # テンプレート未登録

    vars_with_defaults = {"name": customer.name or "お客様", **variables}
    subject = _render(template.subject, vars_with_defaults)
    body_html = _render(template.body_html, vars_with_defaults)
    body_text = _render(template.body_text, vars_with_defaults)

    sent = _send_email(customer.email, subject, body_html, body_text)

    log = EmailLog(
        customer_id=customer_id,
        template_id=template.id,
        subject=subject,
        status="sent" if sent else "queued",
        sent_at=datetime.utcnow(),
    )
    session.add(log)
    await session.commit()
    return True


async def send_purchase_email(
    customer_id: int,
    product_name: str,
    download_url: str,
    order_number: str,
    session: AsyncSession,
):
    """購入直後の配信メール"""
    await send_trigger_email(
        customer_id=customer_id,
        trigger="purchase",
        variables={
            "product_name": product_name,
            "download_url": download_url,
            "order_number": order_number,
        },
        session=session,
    )


async def send_followup_emails_due(session: AsyncSession):
    """
    フォローアップ対象顧客にメール送信（バッチジョブから呼ぶ）
    - 購入3日後: followup_3d
    - 購入7日後: followup_7d
    - 最終購入30日後かつ未購入: reengagement
    """
    from datetime import timedelta

    from src.marketplace.models import Order, OrderStatus

    now = datetime.utcnow()

    async def _send_followup(days: int, trigger: str):
        target_start = now - timedelta(days=days + 1)
        target_end = now - timedelta(days=days)

        result = await session.execute(
            select(Order.customer_id, Order.product_id).where(
                Order.status == OrderStatus.PAID,
                Order.paid_at >= target_start,
                Order.paid_at < target_end,
            ).distinct()
        )
        for customer_id, product_id in result.all():
            from src.products.models import Product
            product = await session.get(Product, product_id)
            await send_trigger_email(
                customer_id=customer_id,
                trigger=trigger,
                variables={"product_name": product.name if product else "商品"},
                session=session,
            )

    await _send_followup(3, "followup_3d")
    await _send_followup(7, "followup_7d")

    # 再エンゲージメント（30日以上購入なし）

    from src.crm.models import CustomerSegment
    reeng_threshold = now - timedelta(days=30)
    churned_result = await session.execute(
        select(Customer).where(
            Customer.segment == CustomerSegment.CHURNED,
            Customer.email_subscribed,
            Customer.last_purchase_at <= reeng_threshold,
        )
    )
    for customer in churned_result.scalars().all():
        await send_trigger_email(
            customer_id=customer.id,
            trigger="reengagement",
            variables={},
            session=session,
        )


async def send_newsletter_blast(
    subject: str,
    body_html: str,
    body_text: str,
    session: AsyncSession,
    segment: Optional[str] = None,
) -> int:
    """
    ニュースレター一斉送信。
    segment=None で全購読者、指定するとセグメント絞り込み。
    送信数を返す。
    """
    query = select(Customer).where(Customer.email_subscribed, Customer.is_active)
    if segment:
        query = query.where(Customer.segment == segment)

    result = await session.execute(query)
    customers = result.scalars().all()
    sent = 0
    for customer in customers:
        vars_ = {"name": customer.name or "お客様"}
        rendered_html = _render(body_html, vars_)
        rendered_text = _render(body_text, vars_)
        rendered_subject = _render(subject, vars_)
        ok = _send_email(customer.email, rendered_subject, rendered_html, rendered_text)
        log = EmailLog(
            customer_id=customer.id,
            subject=rendered_subject,
            status="sent" if ok else "queued",
            sent_at=datetime.utcnow(),
        )
        session.add(log)
        if ok:
            sent += 1

    await session.commit()
    return sent
