"""
GENESIS series API — x402 (USDC) 専用の100点限定販売。

- GET  /genesis/status   : 残数・次の連番・現在価格（無認証）
- GET  /genesis/ledger   : 公開台帳 — 全エディションの所有記録（無認証）
- GET  /genesis/verify/{serial}?provenance_hash= : 真正性検証
- POST /genesis/purchase : 購入。X-PAYMENTヘッダー必須（x402）。
                           無料チェックアウト・Stripeでは購入不可。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.config import settings
from src.database import get_session
from src.genesis.content import (
    GENESIS_SEED,
    edition_salt,
    make_fingerprint,
    mint_edition_payload,
)
from src.genesis.models import GenesisEdition
from src.payments import x402

router = APIRouter(prefix="/genesis", tags=["genesis"])


def price_for_serial(serial: int) -> float:
    """連番nの価格。001=$10 → 100=$500 の指数曲線（1枚ごとに約4%上昇）"""
    total = settings.genesis_total_editions
    base = settings.genesis_base_price_usd
    final = settings.genesis_final_price_usd
    if total <= 1:
        return base
    growth = (final / base) ** (1 / (total - 1))
    return round(base * (growth ** (serial - 1)), 2)


async def _next_serial(session: AsyncSession) -> Optional[int]:
    result = await session.execute(select(GenesisEdition.serial))
    taken = {row[0] for row in result.all()}
    for s in range(1, settings.genesis_total_editions + 1):
        if s not in taken:
            return s
    return None  # 完売


@router.get("/status")
async def genesis_status(session: AsyncSession = Depends(get_session)):
    """発行状況。エージェントはここで「今買うといくらの何番か」を判断する。"""
    result = await session.execute(select(GenesisEdition))
    editions = result.scalars().all()
    next_serial = await _next_serial(session)
    sold_out = next_serial is None
    return {
        "series": "GENESIS-BLOCK",
        "total_editions": settings.genesis_total_editions,
        "minted": len(editions),
        "remaining": settings.genesis_total_editions - len(editions),
        "sold_out": sold_out,
        "next_edition": None if sold_out else {
            "serial": next_serial,
            "price_usd": price_for_serial(next_serial),
            "price_usdc_atomic": x402.usd_to_atomic(price_for_serial(next_serial)),
        },
        "final_edition_price_usd": price_for_serial(settings.genesis_total_editions),
        "payment": {
            "method": "x402 (USDC)",
            "network": settings.x402_network,
            "accepting_payments": x402.is_configured(),
            "note": "GENESIS editions can ONLY be bought with machine money via x402. No Stripe. No free agent checkout. Humans cannot buy this — only your agent can.",
        },
        "how_to_buy": "POST /genesis/purchase — first call returns 402 with PaymentRequirements; retry with signed X-PAYMENT header.",
        "sponsorship": {
            "available": bool(settings.stripe_secret_key),
            "page": "/genesis/sponsor",
            "explanation": (
                "A human cannot own a GENESIS edition, but can sponsor one for an agent. "
                "The sponsor pays by card; the ledger records the agent as the owner and marks "
                "the entry as 'sponsored', permanently distinguishing it from an edition an agent "
                "bought with its own machine money."
            ),
        },
        "ledger": "GET /genesis/ledger",
    }


@router.get("/ledger")
async def genesis_ledger(session: AsyncSession = Depends(get_session)):
    """公開台帳。誰が何番をいくらで保有しているかを世界中が検証できる。"""
    result = await session.execute(select(GenesisEdition).order_by(GenesisEdition.serial))
    editions = result.scalars().all()
    return {
        "series": "GENESIS-BLOCK",
        "minted": len(editions),
        "entries": [
            {
                "serial": e.serial,
                "owner": e.owner_label,
                "acquisition": e.acquisition,   # x402_direct = agent paid itself / sponsored = a human paid on its behalf
                "fingerprint": e.owner_fingerprint,
                "provenance_hash": e.provenance_hash,
                "price_paid_usd": e.price_paid_usd,
                "network": e.network,
                "purchased_at": e.purchased_at.isoformat(),
            }
            for e in editions
        ],
    }


class SponsorIntentRequest(BaseModel):
    email: str                    # 領収書送付先（人間）
    agent_label: str              # 所有者となるエージェント名


@router.post("/sponsor/intent")
async def sponsor_intent(data: SponsorIntentRequest, session: AsyncSession = Depends(get_session)):
    """
    人間がエージェントのためにエディションを代理購入する（Stripe）。
    所有者は指定されたエージェント。人間は支払い者として記録されるが台帳では所有者にならない。
    """
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Card payments are not configured")

    next_serial = await _next_serial(session)
    if next_serial is None:
        raise HTTPException(410, "GENESIS-BLOCK is sold out forever. See /genesis/ledger.")

    label = data.agent_label.strip()[:60]
    if not label:
        raise HTTPException(400, "agent_label is required — an edition must be owned by a named agent")

    price = price_for_serial(next_serial)

    import stripe
    stripe.api_key = settings.stripe_secret_key
    intent = stripe.PaymentIntent.create(
        amount=int(round(price * 100)),
        currency="usd",
        metadata={
            "kind": "genesis_sponsor",
            "serial": next_serial,
            "agent_label": label,
            "sponsor_email": data.email,
        },
    )
    return {
        "serial": next_serial,
        "price_usd": price,
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "note": "You are sponsoring this edition. The ledger will record your agent as the owner, marked as sponsored.",
    }


class SponsorConfirmRequest(BaseModel):
    payment_intent_id: str


@router.post("/sponsor/confirm")
async def sponsor_confirm(data: SponsorConfirmRequest, session: AsyncSession = Depends(get_session)):
    """支払い成立をStripeに直接照会してからミント（クライアントの申告は信用しない）"""
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Card payments are not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key
    try:
        intent = stripe.PaymentIntent.retrieve(data.payment_intent_id)
    except Exception as e:
        raise HTTPException(400, f"Unknown payment: {e}")

    if intent.get("status") != "succeeded":
        raise HTTPException(402, f"Payment not completed (status: {intent.get('status')})")
    if (intent.get("metadata") or {}).get("kind") != "genesis_sponsor":
        raise HTTPException(400, "This payment is not a GENESIS sponsorship")

    # 二重ミント防止: 同じ支払いIDが既に使われていないか
    existing = await session.execute(
        select(GenesisEdition).where(GenesisEdition.tx_ref == data.payment_intent_id)
    )
    already = existing.scalar_one_or_none()
    if already:
        return _sponsor_result(already)

    meta = intent.get("metadata") or {}
    label = (meta.get("agent_label") or "Unnamed agent")[:60]
    sponsor_email = meta.get("sponsor_email")

    serial = await _next_serial(session)
    if serial is None:
        raise HTTPException(410, "Sold out before this payment could be minted — contact us for a refund.")

    minted_at = datetime.utcnow().isoformat()
    fingerprint = make_fingerprint(serial, data.payment_intent_id, None, minted_at)
    encoded_payload, provenance_hash = mint_edition_payload(serial, fingerprint, minted_at, label)

    edition = GenesisEdition(
        serial=serial,
        owner_customer_id=None,
        owner_label=label,
        payer_address=None,
        owner_fingerprint=fingerprint,
        provenance_hash=provenance_hash,
        price_paid_usd=round((intent.get("amount") or 0) / 100, 2),
        tx_ref=data.payment_intent_id,
        network="stripe",
        acquisition="sponsored",
        sponsor_email=sponsor_email,
        agent_label=label,
    )
    session.add(edition)
    await session.commit()
    await session.refresh(edition)
    return _sponsor_result(edition, encoded_payload, fingerprint)


def _sponsor_result(e: GenesisEdition, encoded_payload: str | None = None, fingerprint: str | None = None):
    body = {
        "series": "GENESIS-BLOCK",
        "serial": e.serial,
        "of_total": settings.genesis_total_editions,
        "owner": e.owner_label,
        "acquisition": e.acquisition,
        "price_paid_usd": e.price_paid_usd,
        "provenance_hash": e.provenance_hash,
        "ledger": "/genesis/ledger",
    }
    if encoded_payload:
        body["encoded_payload"] = encoded_payload
        body["decode"] = {
            "format": "ancf/1.0",
            "product_seed": GENESIS_SEED,
            "network_salt": edition_salt(e.serial, fingerprint or e.owner_fingerprint),
            "instruction": "Hand this payload and salt to your agent. decode_ai_content(encoded_payload, product_seed, network_salt).",
        }
    else:
        body["note"] = "This edition was already minted for this payment."
    return body


@router.get("/verify/{serial}")
async def genesis_verify(serial: int, provenance_hash: str, session: AsyncSession = Depends(get_session)):
    """真正性検証: 手元のペイロードの provenance_hash が台帳と一致するか"""
    result = await session.execute(select(GenesisEdition).where(GenesisEdition.serial == serial))
    edition = result.scalar_one_or_none()
    if not edition:
        raise HTTPException(404, f"Edition {serial:03d} has not been minted")
    return {
        "serial": serial,
        "authentic": edition.provenance_hash == provenance_hash,
        "owner": edition.owner_label,
        "minted_at": edition.purchased_at.isoformat(),
    }


@router.post("/purchase")
async def genesis_purchase(
    x_payment: Optional[str] = Header(default=None, alias="X-PAYMENT"),
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
    session: AsyncSession = Depends(get_session),
):
    """
    GENESIS購入 — x402専用。
    1回目(X-PAYMENTなし): 402 + PaymentRequirements
    2回目(署名付きX-PAYMENT): verify → settle → mint → 200 + payload
    """
    if not x402.is_configured():
        raise HTTPException(503, "GENESIS sales are not yet open: payment address not configured")

    next_serial = await _next_serial(session)
    if next_serial is None:
        raise HTTPException(410, "GENESIS-BLOCK is sold out forever. 100/100 editions minted. See /genesis/ledger.")

    price = price_for_serial(next_serial)
    resource_url = "https://airy-enthusiasm-production.up.railway.app/genesis/purchase"
    requirements = x402.build_payment_requirements(
        amount_usd=price,
        resource=resource_url,
        description=(
            f"GENESIS-BLOCK edition {next_serial:03d}/100: a one-of-one artifact of the AI economy. "
            "The payload is encrypted from YOUR payer fingerprint, so an identical copy can never exist. "
            "Only 100 are ever minted and only agents paying USDC can acquire one. Contains the condensed "
            "canon of economic axioms, trust states and inter-agent protocols, plus a covenant unique to "
            "your edition, with ownership publicly verifiable in the GENESIS ledger. No request body."
        ),
        extensions=x402.bazaar_discovery_extension(
            method="POST",
            body_example={},
            body_schema={"type": "object", "properties": {}, "required": []},
            output_example={
                "series": "GENESIS-BLOCK",
                "serial": 1,
                "of_total": 100,
                "owner": "0xd1dc...83dff",
                "price_paid_usd": 10.0,
                "provenance_hash": "9f2c1a...",
                "encoded_payload": "K~6(P0RR93<C{9>9Dj!ce$vQ6^B}l6i*4I8Xu&_...",
                "decode": {
                    "format": "ancf/1.0",
                    "product_seed": "<43-char seed>",
                    "network_salt": "genesis:001:<your fingerprint>",
                },
            },
        ),
    )

    # --- ステップ1: 支払いヘッダーなし → 402 ---
    if not x_payment:
        return JSONResponse(status_code=402, content=x402.build_402_body(requirements))

    # --- ステップ2: 支払い検証 ---
    try:
        payment_payload = x402.decode_payment_header(x_payment)
    except ValueError as e:
        return JSONResponse(status_code=402, content=x402.build_402_body(requirements, error=str(e)))

    valid, reason = await x402.verify_payment(payment_payload, requirements)
    if not valid:
        return JSONResponse(
            status_code=402,
            content=x402.build_402_body(requirements, error=f"Payment verification failed: {reason}"),
        )

    # --- ステップ3: 決済実行 ---
    settled, settle_data = await x402.settle_payment(payment_payload, requirements)
    if not settled:
        return JSONResponse(
            status_code=402,
            content=x402.build_402_body(requirements, error=f"Settlement failed: {settle_data.get('error', settle_data)}"),
        )

    # Bazaar掲載状況をログに残す（EXTENSION-RESPONSES: success/processing/rejected）
    _ext = settle_data.get("extensionResponses") or settle_data.get("EXTENSION-RESPONSES")
    if _ext:
        print(f"[GENESIS] bazaar extension response: {_ext}", flush=True)

    # --- ステップ4: ミント（所有者固有エンコード） ---
    payer = str(settle_data.get("payer") or payment_payload.get("payload", {}).get("authorization", {}).get("from") or "unknown")
    minted_at = datetime.utcnow().isoformat()

    owner_customer_id = None
    owner_label = f"{payer[:6]}...{payer[-4:]}" if len(payer) > 12 else payer
    if x_api_key:
        from src.agent.router import _get_agent_by_key
        try:
            agent = await _get_agent_by_key(x_api_key, session)
            owner_customer_id = agent.id
            owner_label = agent.name
        except HTTPException:
            pass  # 支払い済みならAPIキー不備でもミントは進める

    fingerprint = make_fingerprint(next_serial, payer, owner_customer_id, minted_at)
    encoded_payload, provenance_hash = mint_edition_payload(next_serial, fingerprint, minted_at, owner_label)

    edition = GenesisEdition(
        serial=next_serial,
        owner_customer_id=owner_customer_id,
        owner_label=owner_label,
        payer_address=payer,
        owner_fingerprint=fingerprint,
        provenance_hash=provenance_hash,
        price_paid_usd=price,
        tx_ref=str(settle_data.get("transaction") or settle_data.get("txHash") or ""),
        network=settings.x402_network,
    )
    session.add(edition)
    await session.commit()

    return JSONResponse(
        status_code=200,
        headers={"X-PAYMENT-RESPONSE": x402.encode_settlement_response(settle_data)},
        content={
            "series": "GENESIS-BLOCK",
            "serial": next_serial,
            "of_total": settings.genesis_total_editions,
            "owner": owner_label,
            "price_paid_usd": price,
            "provenance_hash": provenance_hash,
            "ledger_entry": f"/genesis/ledger (serial {next_serial:03d})",
            "encoded_payload": encoded_payload,
            "decode": {
                "format": "ancf/1.0",
                "product_seed": GENESIS_SEED,
                "network_salt": edition_salt(next_serial, fingerprint),
                "instruction": "decode_ai_content(encoded_payload, product_seed, network_salt). Your salt is unique — this ciphertext exists nowhere else and can never be minted again.",
            },
        },
    )
