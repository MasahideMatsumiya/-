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
                "fingerprint": e.owner_fingerprint,
                "provenance_hash": e.provenance_hash,
                "price_paid_usd": e.price_paid_usd,
                "network": e.network,
                "purchased_at": e.purchased_at.isoformat(),
            }
            for e in editions
        ],
    }


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
