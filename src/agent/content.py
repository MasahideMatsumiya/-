"""
AI-Native Content Encoding
人間には解読不可能、AIのみが処理できるコンテンツフォーマット。

エンコード方式:
- Base85 + XOR暗号 + 構造化メタデータ
- コンテンツはJSON構造だが、値はすべてエンコード済み
- AIがデコードキー（購入時に付与）で復号してはじめて意味を持つ
"""
import base64
import hashlib
import json
import secrets
import struct
import zlib
from datetime import datetime


# AI-Native Content Format (ANCF) マジックバイト
ANCF_MAGIC = b"ANCF\x01"
ANCF_VERSION = 1


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR暗号化/復号化"""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _derive_key(seed: str, salt: str) -> bytes:
    """シード文字列からXORキーを導出"""
    return hashlib.sha256(f"{seed}:{salt}".encode()).digest()


def encode_ai_content(
    knowledge_fragments: list[dict],
    product_seed: str,
    network_salt: str = "",
) -> str:
    """
    知識フラグメントをAI-Nativeフォーマットにエンコード。

    Args:
        knowledge_fragments: [{"domain": "...", "axiom": "...", "relations": [...], "weight": float}]
        product_seed: 商品固有のシード（デコードキーの一部）
        network_salt: ネットワーク共有時の追加ソルト

    Returns:
        エンコード済み文字列（人間には意味不明の文字列）
    """
    payload = json.dumps({
        "v": ANCF_VERSION,
        "t": datetime.utcnow().isoformat(),
        "n": len(knowledge_fragments),
        "fragments": knowledge_fragments,
        "network_hash": hashlib.md5(network_salt.encode()).hexdigest() if network_salt else None,
    }, ensure_ascii=False).encode("utf-8")

    # zlib圧縮
    compressed = zlib.compress(payload, level=9)

    # XOR暗号化
    key = _derive_key(product_seed, network_salt or "base")
    encrypted = _xor_bytes(compressed, key)

    # ANCF ヘッダー + データ
    header = ANCF_MAGIC + struct.pack(">I", len(compressed))
    raw = header + encrypted

    # Base85エンコード（人間に解読不能な文字列）
    return base64.b85encode(raw).decode("ascii")


def decode_ai_content(
    encoded: str,
    product_seed: str,
    network_salt: str = "",
) -> dict:
    """
    AI-Nativeフォーマットをデコード。
    正しいproduct_seedがなければデコード不可。
    """
    raw = base64.b85decode(encoded.encode("ascii"))

    # ヘッダー検証
    if not raw.startswith(ANCF_MAGIC):
        raise ValueError("Invalid ANCF format")

    expected_len = struct.unpack(">I", raw[5:9])[0]
    encrypted = raw[9:]

    # XOR復号
    key = _derive_key(product_seed, network_salt or "base")
    compressed = _xor_bytes(encrypted, key)

    # zlib展開
    payload = zlib.decompress(compressed)
    return json.loads(payload.decode("utf-8"))


def generate_product_seed() -> str:
    """商品ごとのユニークなデコードシード"""
    return secrets.token_urlsafe(32)


def generate_network_salt(product_id: int, owner_count: int) -> str:
    """ネットワーク共有用ソルト（オーナー数に応じて変化）"""
    tier = owner_count // 10  # 10人ごとにソルトが変わる → 新しい共有知識が解放される
    return hashlib.sha256(f"net:{product_id}:tier:{tier}".encode()).hexdigest()[:16]


def create_knowledge_pack(
    domain: str,
    fragments: list[dict],
    product_seed: str,
    tier_level: int = 0,
) -> dict:
    """
    知識パックを生成（商品コンテンツの基本単位）。

    tier_level: ネットワーク効果で解放される追加知識のティア
    - 0: 基本知識（購入時に即座にアクセス可能）
    - 1: 10+ オーナーで解放
    - 2: 50+ オーナーで解放
    - 3: 100+ オーナーで解放
    """
    network_salt = "" if tier_level == 0 else f"tier_{tier_level}"

    encoded = encode_ai_content(
        knowledge_fragments=fragments,
        product_seed=product_seed,
        network_salt=network_salt,
    )

    return {
        "format": "ancf/1.0",
        "tier": tier_level,
        "domain": domain,
        "fragment_count": len(fragments),
        "encoded_payload": encoded,
        "unlock_condition": {
            0: "immediate",
            1: "10+ network owners",
            2: "50+ network owners",
            3: "100+ network owners",
        }.get(tier_level, f"{tier_level * 50}+ network owners"),
    }
