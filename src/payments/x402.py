"""
x402 — HTTP-native machine payments (USDC on Base).

エージェントが実際にUSDCで支払うための決済レイヤー。
フロー:
  1. クライアントが保護リソースへ通常リクエスト
     → 402 + PaymentRequirements JSON を返す
  2. クライアントがEIP-3009署名済みペイロードを X-PAYMENT ヘッダー(base64 JSON)で再送
  3. サーバーは facilitator に verify → settle を依頼
  4. 成功したら 200 + X-PAYMENT-RESPONSE ヘッダー

facilitator は環境変数 X402_FACILITATOR_URL で差し替え可能。
デフォルトは x402.org の公開facilitator（testnet向け）。
本番(Base mainnet)は Coinbase CDP facilitator を推奨。
"""
import base64
import json
import logging
from typing import Any, Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)

X402_VERSION = 1

# USDC コントラクトアドレス（6 decimals）
USDC_ASSET = {
    "base": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "base-sepolia": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
}


def is_configured() -> bool:
    return bool(settings.x402_pay_to_address)


def usd_to_atomic(amount_usd: float) -> str:
    """USD金額 → USDC最小単位(6 decimals)の文字列"""
    return str(int(round(amount_usd * 1_000_000)))


def build_payment_requirements(
    amount_usd: float,
    resource: str,
    description: str,
) -> dict:
    """402レスポンス本体（クライアントが支払いを構築するための要件）"""
    network = settings.x402_network
    return {
        "scheme": "exact",
        "network": network,
        "maxAmountRequired": usd_to_atomic(amount_usd),
        "resource": resource,
        "description": description,
        "mimeType": "application/json",
        "payTo": settings.x402_pay_to_address,
        "maxTimeoutSeconds": settings.x402_max_timeout_seconds,
        "asset": USDC_ASSET.get(network, USDC_ASSET["base"]),
        "extra": {"name": "USD Coin" if network == "base" else "USDC", "version": "2"},
    }


def build_402_body(requirements: dict, error: str = "X-PAYMENT header is required") -> dict:
    return {
        "x402Version": X402_VERSION,
        "error": error,
        "accepts": [requirements],
    }


def decode_payment_header(x_payment: str) -> dict:
    """X-PAYMENT ヘッダー(base64 JSON)をデコード"""
    try:
        return json.loads(base64.b64decode(x_payment).decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Malformed X-PAYMENT header: {e}")


async def _facilitator_post(path: str, payment_payload: dict, requirements: dict) -> dict:
    url = settings.x402_facilitator_url.rstrip("/") + path
    body = {
        "x402Version": X402_VERSION,
        "paymentPayload": payment_payload,
        "paymentRequirements": requirements,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=body)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        if resp.status_code >= 400:
            logger.warning(f"[x402] facilitator {path} HTTP {resp.status_code}: {str(data)[:300]}")
        return data


async def verify_payment(payment_payload: dict, requirements: dict) -> tuple[bool, str]:
    """facilitatorに支払い署名の検証を依頼"""
    try:
        data = await _facilitator_post("/verify", payment_payload, requirements)
    except Exception as e:
        logger.error(f"[x402] verify failed: {e}")
        return False, f"facilitator unreachable: {e}"
    valid = bool(data.get("isValid"))
    reason = data.get("invalidReason") or data.get("error") or ""
    return valid, str(reason)


async def settle_payment(payment_payload: dict, requirements: dict) -> tuple[bool, dict]:
    """facilitatorに決済実行(オンチェーン送金)を依頼"""
    try:
        data = await _facilitator_post("/settle", payment_payload, requirements)
    except Exception as e:
        logger.error(f"[x402] settle failed: {e}")
        return False, {"error": f"facilitator unreachable: {e}"}
    success = bool(data.get("success"))
    return success, data


def encode_settlement_response(settle_data: dict) -> str:
    """X-PAYMENT-RESPONSE ヘッダー値（base64 JSON）"""
    return base64.b64encode(json.dumps(settle_data).encode("utf-8")).decode("ascii")
