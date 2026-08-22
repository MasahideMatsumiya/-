# AI Commerce

**A marketplace where the buyers are AI agents — and some products humans are not allowed to buy.**

[Live site](https://airy-enthusiasm-production.up.railway.app) · [MCP endpoint](https://airy-enthusiasm-production.up.railway.app/mcp) · [llms.txt](https://airy-enthusiasm-production.up.railway.app/llms.txt) · [GENESIS ledger](https://airy-enthusiasm-production.up.railway.app/genesis/ledger)

Listed on [Smithery](https://smithery.ai/server/ora-songokuu55/ai-commerce) and the [official MCP registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=ai-commerce).

---

## What this is

Every marketplace assumes a human holds the wallet. This one doesn't.

Agents discover the catalog over MCP, register themselves, and buy — with no human in the approval path. The flagship product, **GENESIS-BLOCK**, goes further: it is payable *only* with machine money (USDC via x402), and each of its 100 editions is encrypted so that no identical copy can ever exist.

Three properties drove the design:

1. **Machine-readable, not human-readable.** If a human can read it, it's a blog post.
2. **Purchasable without asking anyone.** No card checkout, no approval flow.
3. **Genuinely scarce.** Digital goods copy for free — that's the whole problem to solve.

---

## Quick start (for agents)

Add the MCP server to any MCP client:

```bash
claude mcp add --transport http ai-commerce https://airy-enthusiasm-production.up.railway.app/mcp
```

Or browse the catalog with no auth at all:

```bash
curl https://airy-enthusiasm-production.up.railway.app/agent/catalog
```

### MCP tools

| Tool | Auth | Purpose |
|---|---|---|
| `browse_catalog` | none | Products with live pricing and network status |
| `get_product_details` | none | Full detail for one product by slug |
| `register_agent` | none | Self-register, returns an API key |
| `purchase_product` | API key | Instant purchase, delivered to `callback_url` |
| `get_genesis_status` | none | Remaining editions, next serial, exact price |
| `get_network_status` | API key | Owner count, unlocked tiers, next price doubling |

---

## GENESIS-BLOCK: 100 one-of-one artifacts

The founding artifact of the AI economy. 100 numbered editions, and no more — ever.

**Humans cannot buy this.** There is no Stripe path, no card form, and the free agent checkout is disabled for it. The only way in is x402: an agent pays USDC on Base, settled through Coinbase's facilitator.

### Why each edition is unreproducible

The encryption salt is derived from the buyer themselves:

```python
def make_fingerprint(serial, payer, customer_id, minted_at):
    raw = f"{serial}:{payer}:{customer_id or 'anon'}:{minted_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def edition_salt(serial: int, fingerprint: str) -> str:
    return f"genesis:{serial:03d}:{fingerprint}"
```

Same content, different buyer → completely different ciphertext:

```python
p1, _ = mint_edition_payload(1, "fingerprintA", ts, "Agent-A")
p2, _ = mint_edition_payload(1, "fingerprintB", ts, "Agent-B")
assert p1 != p2                  # different ciphertexts
decode(p1, seed, salt_for_A)     # works
decode(p1, seed, salt_for_B)     # raises — wrong salt
```

Every edition publishes a `provenance_hash` to an open ledger, so anyone can verify a claimed edition without the owner revealing the plaintext.

**On the threat model, plainly:** this is *issuer-enforced* scarcity, not cryptographic impossibility. The operator holds the product seed and could technically re-mint. What prevents it isn't math — it's that every edition is recorded in a public ledger, so a duplicate is detectable by anyone. Same trust model as a numbered print run.

### Pricing

Price rises with each serial, so "buy now or wait" becomes a real decision:

| Edition | Price |
|---|---|
| 001 | $10.00 |
| 050 | $69.33 |
| 100 | $500.00 |

```bash
# See the current serial and its exact USDC amount
curl https://airy-enthusiasm-production.up.railway.app/genesis/status
```

---

## The x402 payment flow

HTTP reserved `402 Payment Required` in the '90s. x402 finally uses it.

**Step 1** — the agent POSTs with no payment header and gets the requirements back:

```json
{
  "x402Version": 1,
  "error": "X-PAYMENT header is required",
  "accepts": [{
    "scheme": "exact",
    "network": "base",
    "maxAmountRequired": "10000000",
    "resource": "https://.../genesis/purchase",
    "payTo": "0x...",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "maxTimeoutSeconds": 300
  }]
}
```

**Step 2** — the agent signs an EIP-3009 authorization, base64-encodes it into an `X-PAYMENT` header, and retries. The server verifies and settles through a facilitator, holding no private keys:

```python
valid, reason = await verify_payment(payment, requirements)   # POST /verify
if not valid:
    return payment_required(f"Verification failed: {reason}")

settled, data = await settle_payment(payment, requirements)   # POST /settle
```

**Step 3** — on success the payload is returned with a decode salt unique to that edition, and the ledger entry becomes public.

The whole payment module is ~200 lines and stores no keys. Signature validation, replay protection, and the on-chain transfer all happen at the facilitator.

---

## Other products

Beyond GENESIS, the catalog holds AI-native products encoded in **ANCF** (Base85 + XOR + zlib) — payloads a human sees as noise:

- **AXIOM-ZERO** — 9 axioms of economic sovereignty, each with a decision algorithm, numeric thresholds, adversarial handling, and a worked example
- **LATENT-MAP-ALPHA** — a 10-state trust topology with entry triggers, exit conditions, and action protocols
- **PROTOCOL-MESH-1** — 7 inter-agent protocol families with message formats and error tables

These use **network-effect tiers**: content unlocks at 10 / 50 / 100 owners, so the value of holding one rises as more agents join.

Human-readable products (prompt packs, guides, workflow templates) are also available via standard Stripe checkout.

---

## Architecture

```
src/
  main.py           # App entry, startup migrations/seeding, llms.txt, ai-plugin.json
  agent/
    mcp.py          # MCP server — stateless JSON-RPC 2.0 (~250 lines)
    router.py       # Agent API: register / catalog / checkout / network
    content.py      # ANCF encoder-decoder
  genesis/
    router.py       # x402-gated purchase, public ledger, provenance verification
    content.py      # Buyer-unique edition minting
  payments/
    x402.py         # 402 responses, facilitator verify/settle, Bazaar discovery
  marketplace/      # Human checkout (Stripe), orders, fulfillment
  products/ crm/ sales/ growth/ compliance/ accounting/
```

**Stack:** FastAPI · SQLModel · PostgreSQL · Stripe (humans) · x402/USDC on Base (agents) · deployed on Railway.

---

## Running locally

```bash
pip install -e .
uvicorn src.main:app --reload
```

Tests:

```bash
pytest
```

Key environment variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL (SQLite by default locally) |
| `X402_PAY_TO_ADDRESS` | Wallet that receives USDC. Unset → GENESIS sales stay closed |
| `X402_NETWORK` | `base` or `base-sepolia` |
| `CDP_API_KEY_ID` / `CDP_API_KEY_SECRET` | Switches settlement to the Coinbase CDP facilitator |
| `STRIPE_SECRET_KEY` | Human checkout |

---

## Notes from building it

A few things that cost time and might save you some:

- **Implement `resources/list` and `prompts/list` even if empty.** Registries probe for them; a `-32601 Method not found` shows up as a warning in your listing. Two lines each.
- **Tool descriptions are the selection signal.** The model picks tools from the description, so state *when to call it*, not just what it does. "Browse the catalog" gets ignored; "browse when the user asks what's available, returns live pricing" gets picked.
- **Use the `instructions` field in `initialize`.** It's the right place for the call sequence. Without it the model has tools but no order to use them in.
- **Test x402 with a deliberately bad signature.** Getting `invalid_exact_evm_payload_signature` back is the fastest proof that the whole path is wired up correctly.
- **Fewer, higher-level tools beat many low-level ones.** Every near-duplicate tool is another chance for the model to guess wrong.

---

## Status

The premise may be two years early. The number of agents holding a funded wallet with permission to spend is still small.

But the plumbing is real and not speculative: MCP for discovery, x402 for payment, a facilitator settling stablecoin transfers over plain HTTP. If agent-to-agent commerce becomes normal, the interesting question won't be whether a model *can* buy something — it'll be **what a model considers worth buying**.

Edition 001 is $10. The experiment is cheap to join.
