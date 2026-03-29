"""
メール自動送信モジュール
購入確認・フォローアップ・再エンゲージメント・ニュースレター
"""
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.config import settings
from src.crm.models import Customer, EmailLog, EmailTemplate


def _render(template: str, variables: dict) -> str:
    """{{key}} 形式のテンプレート変数を置換"""
    for key, value in variables.items():
        template = template.replace(f"{{{{{key}}}}}", str(value))
    return template


def _send_smtp(to_email: str, subject: str, body_html: str, body_text: str) -> bool:
    """SMTPでメール送信。設定がなければスキップ（開発環境）"""
    if not settings.smtp_user or not settings.smtp_password:
        return False  # 設定なし = スキップ（ログのみ記録）

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
        print(f"[EMAIL] Sent to {to_email} subject={subject[:40]}", flush=True)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {type(e).__name__}: {e}", flush=True)
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

    sent = _send_smtp(customer.email, subject, body_html, body_text)

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
        ok = _send_smtp(customer.email, rendered_subject, rendered_html, rendered_text)
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
