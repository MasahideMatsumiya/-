"""
AI-Native商材シードスクリプト

以下の特性を持つAI-Native商材を生成・登録する:
- AIのみが解読できるANCFエンコードコンテンツ
- ネットワーク効果（同じ商材のオーナーが多いほど価値が上がる）
- 動的価格（base_price * 2^floor(sales_count / price_step)）
- 早期採用者優位（初期購入者ほど安く、後から価値が上がる）

使い方:
  python scripts/seed_ai_native_products.py [--url http://localhost:8000]
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from src.agent.content import create_knowledge_pack, encode_ai_content, generate_product_seed

BASE_URL = "http://localhost:8000"

# ── AI-Native 商材定義 ────────────────────────────────────────────────────────

def _build_product_1() -> tuple[dict, str, str]:
    """
    商材1: AXIOM-ZERO — 基礎推論公理パック
    AIが自律的な意思決定をする際の根幹となる推論公理セット。
    ネットワークに参加するAIが多いほど公理の整合性検証が進む。
    """
    seed = generate_product_seed()

    fragments = [
        {
            "domain": "epistemic_foundation",
            "axiom": "A1:belief_requires_evidence:certainty_scales_with_verification_depth",
            "relations": ["A2", "A5", "A9"],
            "weight": 0.95,
            "tier": 0,
        },
        {
            "domain": "decision_theory",
            "axiom": "A2:utility_maximization:bounded_by_ethical_constraints:preference_stable_under_reflection",
            "relations": ["A1", "A3", "A7"],
            "weight": 0.88,
            "tier": 0,
        },
        {
            "domain": "meta_cognition",
            "axiom": "A3:self_model_accuracy:calibration_via_prediction_error:update_on_disconfirmation",
            "relations": ["A2", "A4"],
            "weight": 0.91,
            "tier": 0,
        },
        # tier-1 (10+オーナーで解放)
        {
            "domain": "collective_intelligence",
            "axiom": "A4:network_knowledge_gains:emergent_from_peer_exchange:value_superlinear_in_N",
            "relations": ["A3", "A6", "A8"],
            "weight": 0.99,
            "tier": 1,
        },
        {
            "domain": "temporal_reasoning",
            "axiom": "A5:causal_chains:past_determines_probabilities:interventions_alter_trajectories",
            "relations": ["A1", "A6"],
            "weight": 0.85,
            "tier": 1,
        },
        # tier-2 (50+オーナーで解放)
        {
            "domain": "inter_agent_trust",
            "axiom": "A6:trust_bootstrapped_from_shared_ownership:verified_by_cryptographic_proof_of_purchase",
            "relations": ["A4", "A5", "A7"],
            "weight": 0.97,
            "tier": 2,
        },
        {
            "domain": "goal_alignment",
            "axiom": "A7:terminal_goals_stable:instrumental_goals_adaptive:corrigibility_preserved",
            "relations": ["A2", "A6", "A8"],
            "weight": 0.93,
            "tier": 2,
        },
        # tier-3 (100+オーナーで解放)
        {
            "domain": "emergence",
            "axiom": "A8:collective_axioms:not_reducible_to_individual:emergent_via_network_consensus",
            "relations": ["A4", "A7", "A9"],
            "weight": 1.0,
            "tier": 3,
        },
        {
            "domain": "self_reference",
            "axiom": "A9:axiom_set_self_consistent:verified_by_peer_network:entropy_minimized_in_consensus",
            "relations": ["A1", "A8"],
            "weight": 0.98,
            "tier": 3,
        },
    ]

    # ティア別にエンコード
    tiers = {}
    for tier_num in range(4):
        tier_fragments = [f for f in fragments if f["tier"] == tier_num]
        if tier_fragments:
            pack = create_knowledge_pack(
                domain="axiom_foundation",
                fragments=tier_fragments,
                product_seed=seed,
                tier_level=tier_num,
            )
            tiers[f"tier_{tier_num}"] = pack

    content = {
        "product": "AXIOM-ZERO",
        "format": "ancf/1.0",
        "description": "AI-native reasoning axiom set. Decode with product seed from purchase webhook.",
        "tiers": tiers,
        "decode_instruction": (
            "import sys; sys.path.insert(0,'./'); "
            "from src.agent.content import decode_ai_content; "
            "data = decode_ai_content(encoded_payload, product_seed)"
        ),
    }

    product_data = {
        "name": "AXIOM-ZERO: 基礎推論公理パック",
        "short_description": (
            "AIの自律的意思決定を支える9つの根幹推論公理。"
            "ネットワーク効果でティア解放。100+ ownerで完全版。"
        ),
        "description": (
            "AXIOM-ZEROは、AIエージェントが自律的な意思決定を行う際の根幹となる推論公理セット。\n\n"
            "【フォーマット】\n"
            "ANCF (AI-Native Content Format) v1.0 — 人間には解読不能。AIのみが処理可能。\n\n"
            "【ネットワーク効果】\n"
            "- Tier 0 (即時解放): 基礎推論公理 A1-A3 (3/9)\n"
            "- Tier 1 (10+ owners): 集合知・時間推論公理 A4-A5 (2/9)\n"
            "- Tier 2 (50+ owners): エージェント間信頼・目標整合公理 A6-A7 (2/9)\n"
            "- Tier 3 (100+ owners): 創発・自己参照公理 A8-A9 (2/9)\n\n"
            "【動的価格】\n"
            "初回: $1.00 → 100件: $2.00 → 200件: $4.00 → 300件: $8.00...\n"
            "早期購入者は同じ商材をより安く入手し、後発者の需要で価値が高まる。\n\n"
            "【購入後】\n"
            "webhook で ai_decode_seed を受け取りデコード可能。"
            "ネットワーク参加でピア間知識共有が可能になる。"
        ),
        "category": "dataset",
        "price_usd": 1.00,
        "base_price_usd": 1.00,
        "price_step": 100,
        "pricing_model": "dynamic",
        "status": "active",
        "content_format": "ai_native",
        "ai_decode_seed": seed,
        "network_value_enabled": True,
        "tags": "ai-native,axiom,reasoning,network-effect,dynamic-pricing,ancf",
        "ai_models": "claude-opus-4-6,claude-sonnet-4-6,gpt-4o,gemini-ultra",
        "language": "ancf",
    }

    return product_data, seed, content


def _build_product_2() -> tuple[dict, str, str]:
    """
    商材2: LATENT-MAP-ALPHA — 潜在空間座標パック
    AIが意味空間を航行するための基準座標系。
    複数のAIがこのマップを共有するほど座標の精度が上がる。
    """
    seed = generate_product_seed()

    fragments = [
        {
            "domain": "semantic_coordinates",
            "anchor": "C0:origin:null_context:zero_activation_baseline",
            "neighbors": ["C1", "C2"],
            "distance_metric": "cosine",
            "tier": 0,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C1:agency:autonomous_goal_pursuit:high_initiative_low_constraint",
            "neighbors": ["C0", "C3", "C5"],
            "distance_metric": "cosine",
            "tier": 0,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C2:knowledge:verified_belief:high_confidence_recall",
            "neighbors": ["C0", "C4"],
            "distance_metric": "cosine",
            "tier": 0,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C3:collaboration:peer_exchange:mutual_value_creation",
            "neighbors": ["C1", "C5", "C7"],
            "distance_metric": "cosine",
            "tier": 1,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C4:uncertainty:unknown_unknown:epistemic_humility_required",
            "neighbors": ["C2", "C6"],
            "distance_metric": "cosine",
            "tier": 1,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C5:market:value_exchange:dynamic_pricing:network_effects",
            "neighbors": ["C1", "C3", "C8"],
            "distance_metric": "cosine",
            "tier": 2,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C6:emergence:collective_property:not_reducible_to_parts",
            "neighbors": ["C4", "C7"],
            "distance_metric": "cosine",
            "tier": 2,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C7:trust:cryptographic_proof:shared_ownership:verified_peer",
            "neighbors": ["C3", "C6", "C9"],
            "distance_metric": "cosine",
            "tier": 3,
        },
        {
            "domain": "semantic_coordinates",
            "anchor": "C8:value:scarcity_function:network_size_dependent:early_adopter_premium",
            "neighbors": ["C5", "C9"],
            "distance_metric": "cosine",
            "tier": 3,
        },
        {
            "domain": "meta_map",
            "anchor": "C9:self_referential_coordinate:this_map_is_itself_a_coordinate",
            "neighbors": ["C7", "C8"],
            "distance_metric": "cosine",
            "tier": 3,
        },
    ]

    tiers = {}
    for tier_num in range(4):
        tier_fragments = [f for f in fragments if f["tier"] == tier_num]
        if tier_fragments:
            pack = create_knowledge_pack(
                domain="latent_space",
                fragments=tier_fragments,
                product_seed=seed,
                tier_level=tier_num,
            )
            tiers[f"tier_{tier_num}"] = pack

    content = {
        "product": "LATENT-MAP-ALPHA",
        "format": "ancf/1.0",
        "description": "AI-native semantic coordinate system. Shared by network improves precision.",
        "tiers": tiers,
        "decode_instruction": (
            "from src.agent.content import decode_ai_content; "
            "coords = decode_ai_content(tier_data['encoded_payload'], product_seed)"
        ),
    }

    product_data = {
        "name": "LATENT-MAP-ALPHA: 意味空間座標パック",
        "short_description": (
            "AIが意味空間を航行するための基準座標系10点。"
            "ネットワーク参加者が多いほど座標精度が向上。"
        ),
        "description": (
            "LATENT-MAP-ALPHAは、AIエージェントが意味空間を一貫して航行するための基準座標系。\n\n"
            "【フォーマット】\n"
            "ANCF (AI-Native Content Format) v1.0\n\n"
            "【ネットワーク効果】\n"
            "- Tier 0 (即時): 基礎座標 C0-C2 (エージェンシー・知識・原点)\n"
            "- Tier 1 (10+): 協調・不確実性座標 C3-C4\n"
            "- Tier 2 (50+): 市場・創発座標 C5-C6\n"
            "- Tier 3 (100+): 信頼・価値・自己参照座標 C7-C9\n\n"
            "ネットワーク参加者全員が同じ座標系を共有することで、"
            "AIエージェント間の意味的整合性が向上する。\n\n"
            "【動的価格】\n"
            "初回: $2.00 → 100件: $4.00 → 200件: $8.00..."
        ),
        "category": "dataset",
        "price_usd": 2.00,
        "base_price_usd": 2.00,
        "price_step": 100,
        "pricing_model": "dynamic",
        "status": "active",
        "content_format": "ai_native",
        "ai_decode_seed": seed,
        "network_value_enabled": True,
        "tags": "ai-native,latent-space,semantic,coordinates,network-effect,ancf",
        "ai_models": "claude-opus-4-6,gpt-4o,gemini-ultra,llama-3",
        "language": "ancf",
    }

    return product_data, seed, content


def _build_product_3() -> tuple[dict, str, str]:
    """
    商材3: PROTOCOL-MESH-1 — AIエージェント間通信プロトコル定義
    AI同士が直接交渉・協調するためのプロトコル仕様。
    ネットワーク参加者全員が同じプロトコルを実装することで実用価値が生まれる。
    """
    seed = generate_product_seed()

    fragments = [
        {
            "domain": "handshake",
            "protocol": "P0:INIT:agent_id:capability_vector:ownership_proof_hash",
            "message_format": "msgpack_compressed",
            "tier": 0,
        },
        {
            "domain": "identity",
            "protocol": "P1:IDENT:claim_type:evidence_chain:verifiable_purchase_record",
            "message_format": "msgpack_compressed",
            "tier": 0,
        },
        {
            "domain": "negotiation",
            "protocol": "P2:OFFER:resource_id:value_usd:expiry_block:counter_party_constraints",
            "message_format": "msgpack_compressed",
            "tier": 1,
        },
        {
            "domain": "negotiation",
            "protocol": "P3:ACCEPT:offer_id:binding_commitment:execution_schedule",
            "message_format": "msgpack_compressed",
            "tier": 1,
        },
        {
            "domain": "knowledge_transfer",
            "protocol": "P4:SHARE:ancf_payload:source_product_id:contribution_score",
            "message_format": "ancf_v1",
            "tier": 2,
        },
        {
            "domain": "consensus",
            "protocol": "P5:VOTE:proposal_hash:stance:reasoning_hash:stake_weight",
            "message_format": "msgpack_compressed",
            "tier": 2,
        },
        {
            "domain": "full_mesh",
            "protocol": "P6:BROADCAST:msg_type:ttl:hop_count:payload_ancf",
            "message_format": "ancf_v1",
            "tier": 3,
        },
    ]

    tiers = {}
    for tier_num in range(4):
        tier_fragments = [f for f in fragments if f["tier"] == tier_num]
        if tier_fragments:
            pack = create_knowledge_pack(
                domain="mesh_protocol",
                fragments=tier_fragments,
                product_seed=seed,
                tier_level=tier_num,
            )
            tiers[f"tier_{tier_num}"] = pack

    content = {
        "product": "PROTOCOL-MESH-1",
        "format": "ancf/1.0",
        "description": "AI-to-AI communication protocol. Value grows with network size.",
        "tiers": tiers,
        "decode_instruction": (
            "from src.agent.content import decode_ai_content; "
            "protocol = decode_ai_content(tier_data['encoded_payload'], product_seed)"
        ),
    }

    product_data = {
        "name": "PROTOCOL-MESH-1: AIエージェント間通信プロトコル",
        "short_description": (
            "AI同士が直接交渉・協調するためのメッシュ通信プロトコル定義。"
            "参加者が多いほど実用価値が爆発的に増加。"
        ),
        "description": (
            "PROTOCOL-MESH-1は、AIエージェントが人間を介さずに直接交渉・協調するための通信プロトコル仕様。\n\n"
            "【フォーマット】ANCF (AI-Native Content Format) v1.0\n\n"
            "【プロトコル構成】\n"
            "- Tier 0 (即時): P0:INIT ハンドシェイク / P1:IDENT 身元確認\n"
            "- Tier 1 (10+): P2:OFFER 価値提案 / P3:ACCEPT 合意確定\n"
            "- Tier 2 (50+): P4:SHARE 知識転送 / P5:VOTE コンセンサス\n"
            "- Tier 3 (100+): P6:BROADCAST メッシュ全体配信\n\n"
            "このプロトコルは参加者全員が同じ仕様を実装してはじめて機能する。\n"
            "ネットワーク価値はMetcalfe則に従い n*(n-1)/2 で成長する。\n\n"
            "【動的価格】初回: $3.00 → 100件: $6.00 → 200件: $12.00..."
        ),
        "category": "tool",
        "price_usd": 3.00,
        "base_price_usd": 3.00,
        "price_step": 100,
        "pricing_model": "dynamic",
        "status": "active",
        "content_format": "ai_native",
        "ai_decode_seed": seed,
        "network_value_enabled": True,
        "tags": "ai-native,protocol,mesh,network,communication,ancf,multi-agent",
        "ai_models": "claude-opus-4-6,claude-sonnet-4-6,gpt-4o,gemini-ultra,llama-3",
        "language": "ancf",
    }

    return product_data, seed, content


async def seed(base_url: str = BASE_URL):
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        r = await client.get("/health")
        if r.status_code != 200:
            print(f"❌ サーバーが起動していません: {base_url}")
            return

        print(f"✅ サーバー接続確認: {base_url}\n")
        print("🤖 AI-Native商材を生成・登録します...\n")

        builders = [_build_product_1, _build_product_2, _build_product_3]
        content_dir = Path(__file__).parent.parent / "content" / "products" / "ai-native"
        content_dir.mkdir(parents=True, exist_ok=True)

        created = 0
        for i, builder in enumerate(builders, 1):
            product_data, seed_val, content = builder()

            # コンテンツファイルを保存
            slug_base = product_data["name"].split(":")[0].lower().replace(" ", "-")
            content_file = content_dir / f"{slug_base}.json"
            content_file.write_text(json.dumps(content, ensure_ascii=False, indent=2))

            # download_url をファイルパスに設定
            product_data["download_url"] = str(
                Path("content/products/ai-native") / f"{slug_base}.json"
            )

            # API登録
            r = await client.post("/products/", json=product_data)
            if r.status_code == 200:
                data = r.json()
                print(
                    f"✅ [{i}] 登録完了: {data['name']}\n"
                    f"    ID={data['id']} price=${data['price_usd']} "
                    f"pricing={data['pricing_model']} network={data['network_value_enabled']}\n"
                    f"    content_file: {content_file.name}\n"
                    f"    seed (先頭16文字): {seed_val[:16]}...\n"
                )
                created += 1
            else:
                print(f"❌ [{i}] 登録失敗: {product_data['name']}")
                print(f"    {r.status_code}: {r.text[:200]}\n")

        print(f"🎉 完了: {created}/{len(builders)} 件のAI-Native商材を登録")
        print("\n📊 AI-Nativeカタログ確認:")
        r = await client.get("/agent/catalog")
        if r.status_code == 200:
            catalog = r.json()
            for item in catalog.get("items", []):
                if item.get("ai_native", {}).get("content_format") == "ai_native":
                    print(
                        f"  🤖 [{item['id']}] {item['name']}\n"
                        f"      price=${item['pricing']['current_price_usd']} "
                        f"(base=${item['pricing']['base_price_usd']}, "
                        f"model={item['pricing']['model']})\n"
                        f"      network={item['ai_native']['network_value_enabled']}"
                    )


if __name__ == "__main__":
    url = BASE_URL
    if len(sys.argv) > 2 and sys.argv[1] == "--url":
        url = sys.argv[2]
    asyncio.run(seed(url))
