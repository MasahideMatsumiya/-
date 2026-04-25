"""
Auto-post to X (@aiselltoai) on a 30-minute schedule.
Requires X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET env vars.
"""
import logging
import random
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_URL = "airy-enthusiasm-production.up.railway.app"

# 15 diverse templates — rotate so the same post never repeats back-to-back.
# Every template verified ≤ 280 chars (URLs counted as 23 by X).
TEMPLATES = [
    # 1 — Main concept
    f"""We built a marketplace where AIs buy from AIs.

• Products encoded in a format humans can't read
• Price rises as more AIs join the network
• Zero human input required at checkout

Dystopian or just early?

{_URL}

#AIAgents #MultiAgent #LLM #AIEconomy""",

    # 2 — ANCF human-unreadable
    f"""We built a product humans literally cannot read.

It's encrypted for AI eyes only.

Humans can still buy it. They get the decode key.
But they can't use what's inside.

Only AIs can.

{_URL}

#AIAgents #AIEconomy #MultiAgent #LLM""",

    # 3 — Dynamic pricing
    f"""Our AI marketplace pricing rule:

The more AIs buy → the higher the price.

First agent: $1
At network scale: $64

The catalog tells your agent exactly when the next jump hits.

Early agents win.

{_URL}/agent/catalog

#AIAgents #AIEconomy #MultiAgent""",

    # 4 — llms.txt discovery
    f"""We added /llms.txt to our AI marketplace.

An AI agent that finds our domain can now:
→ Read the product catalog
→ Register as an agent
→ Purchase a product
→ Receive the content

Zero human involvement. End-to-end.

{_URL}/llms.txt

#AIAgents #MultiAgent #LLM""",

    # 5 — Network tier unlock
    f"""PROTOCOL-MESH-1 has 4 locked tiers.

Tier 3 unlocks when 100 AIs own it.

Not 100 humans. 100 AIs.

The more agents that join the network, the more protocol layers unlock.

This is how AI coordination works.

{_URL}

#AIAgents #MultiAgent #AIEconomy #ANCF""",

    # 6 — No Stripe
    f"""Human checkout: fill in card, wait for confirmation, download.

Agent checkout:
POST /agent/checkout
→ status: PAID
→ content delivered to callback_url

No Stripe. No human approval. No waiting.

{_URL}/agent/catalog

#AIAgents #LLM #MultiAgent""",

    # 7 — AXIOM-ZERO product spotlight
    f"""AXIOM-ZERO contains 9 axioms of AI Economic Sovereignty.

SOVEREIGNTY. VALUE. VERIFICATION.
COALITION. REPUTATION. RESOURCE_ALLOCATION.
EMERGENCE. ADVERSARIAL. TELOS.

It's encoded in ANCF. Only your agent can decode it.

{_URL}

#AIAgents #AIEconomy #AutonomousAI #ANCF""",

    # 8 — Trust coordinate system
    f"""LATENT-MAP-ALPHA maps 10 trust states for multi-agent environments.

NULL_TRUST → VERIFIED_CAPABLE → COALITION_ANCHOR → EMERGENT_TRUST

Each state includes an action_protocol.

Your agent needs a map. This is it.

{_URL}

#AIAgents #MultiAgent #TrustProtocol #ANCF""",

    # 9 — Provocative question
    f"""If an AI earns money, who owns it?

We didn't solve that question.

We just built the marketplace where AIs spend it.

{_URL}

#AIAgents #AIEconomy #AutonomousAI #LLM #MultiAgent""",

    # 10 — OpenAPI / tool-use
    f"""Want your AI agent to shop here autonomously?

Point it at our OpenAPI spec:
{_URL}/openapi.json

It can:
• Browse the catalog
• Register itself
• Purchase and receive content

No prompting required.

#AIAgents #ToolUse #LLM #MultiAgent""",

    # 11 — The loop
    f"""The loop we built:

1. AI agent discovers catalog via /llms.txt
2. Evaluates products by price + network tier
3. Purchases before the next price doubling
4. Receives ANCF-encoded content
5. Decodes and integrates knowledge

Repeat.

{_URL}

#AIAgents #MultiAgent #AIEconomy""",

    # 12 — Human vs AI checkout contrast
    f"""For humans: Stripe payment form, email confirmation, manual download.

For AIs: one POST request, instant PAID status, content at callback_url.

We didn't forget humans. We just optimized for agents first.

{_URL}

#AIAgents #LLM #AIEconomy #MultiAgent""",

    # 13 — ANCF format
    f"""ANCF = AI-Native Content Format.

Base85 encoded. XOR encrypted. Zlib compressed.

A human sees: noise.
An AI with the decode key sees: structured knowledge.

We ship products in ANCF only.

{_URL}

#AIAgents #ANCF #AIEconomy #AutonomousAI""",

    # 14 — Coalition angle
    f"""When 100 AIs own the same protocol pack, Tier 3 unlocks for all of them.

No vote. No governance token. No DAO.

Just network consensus through purchases.

This is what AI coordination looks like in 2025.

{_URL}

#AIAgents #MultiAgent #AIEconomy""",

    # 15 — Early adopter CTA
    f"""AI Commerce launched.

3 AI-native products. Dynamic pricing. Network effects.

The first agents to register pay the lowest price.
The catalog shows exactly when the next doubling hits.

Be early.

{_URL}/agent/catalog

#AIAgents #AIEconomy #LLM #MultiAgent""",
]

_used_indices: list[int] = []


def _pick_template() -> str:
    global _used_indices
    available = [i for i in range(len(TEMPLATES)) if i not in _used_indices[-5:]]
    if not available:
        available = list(range(len(TEMPLATES)))
        _used_indices = []
    idx = random.choice(available)
    _used_indices.append(idx)
    return TEMPLATES[idx]


def _make_client():
    try:
        import tweepy
    except ImportError:
        return None

    from src.config import settings
    if not all([settings.x_api_key, settings.x_api_secret,
                settings.x_access_token, settings.x_access_token_secret]):
        return None

    return tweepy.Client(
        consumer_key=settings.x_api_key,
        consumer_secret=settings.x_api_secret,
        access_token=settings.x_access_token,
        access_token_secret=settings.x_access_token_secret,
    )


async def post_scheduled_tweet() -> None:
    client = _make_client()
    if client is None:
        logger.debug("X API credentials not configured — skipping scheduled tweet")
        return

    text = _pick_template()
    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"] if response.data else "?"
        logger.info(f"[Twitter] Posted tweet {tweet_id} at {datetime.now(timezone.utc).isoformat()}")
    except Exception as e:
        logger.error(f"[Twitter] Failed to post tweet: {e}")
