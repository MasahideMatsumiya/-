---
title: I built a product that humans are not allowed to buy
published: false
tags: ai, mcp, python, web3
---

I shipped something last week that I still can't decide is early or absurd: a digital artifact that **only an AI agent can purchase**. No card checkout. No "sign in with Google." If you are a human, there is no path to owning one.

This post is about how it works and what I learned building it — the MCP server, the x402 payment layer, and the encryption trick that makes each copy impossible to reproduce.

## The premise

Every marketplace assumes a human is holding the wallet. But agents increasingly have tool access, budgets, and the ability to make purchase decisions. So I asked a narrower question:

> If the customer is a model, what does a product even look like?

Three properties fell out of that:

1. **It should be machine-readable, not human-readable.** If a human can read it, it's a blog post.
2. **The agent should be able to buy it without asking anyone.** No approval flow, no Stripe redirect.
3. **It should be genuinely scarce.** Digital goods copy for free — that's the whole problem.

## 1. Discovery: an MCP server

Agents can't buy what they can't find. The marketplace is exposed as a Streamable-HTTP MCP server, so any MCP client can add it and the model can browse on its own.

```
claude mcp add --transport http ai-commerce https://your-host/mcp
```

The MCP layer is stateless JSON-RPC 2.0 — about 250 lines of Python. No framework, no SDK on the hot path:

```python
async def _handle_rpc(msg: dict) -> Optional[dict]:
    method = msg.get("method", "")
    req_id = msg.get("id")

    if req_id is None:
        return None  # notification — no response

    if method == "initialize":
        return _rpc_result(req_id, {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ai-commerce", "version": "1.0.0"},
            "instructions": "browse_catalog → register_agent → purchase_product",
        })

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        result = await _call_tool(params["name"], params.get("arguments") or {})
        return _rpc_result(req_id, {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            "isError": False,
        })

    return _rpc_error(req_id, -32601, f"Method not found: {method}")
```

**Lesson 1: implement `resources/list` and `prompts/list` even if you have none.** Return empty arrays. Registries probe for them, and a `-32601 Method not found` shows up as a warning in your listing. Two lines each:

```python
if method == "resources/list":
    return _rpc_result(req_id, {"resources": []})
if method == "prompts/list":
    return _rpc_result(req_id, {"prompts": []})
```

**Lesson 2: tool descriptions are your sales copy.** The model chooses tools based on the description string. Ours doesn't just say "browse products" — it says prices rise as more agents buy, which turns a passive lookup into a timing decision.

## 2. Payment: x402 (HTTP 402, finally used for its actual purpose)

HTTP has had a `402 Payment Required` status code reserved since the '90s. x402 finally uses it: the server returns 402 with machine-readable payment requirements, the client pays in USDC, and retries.

Server side, this is simpler than it looks. First call — no payment header:

```python
if not x_payment:
    return JSONResponse(status_code=402, content={
        "x402Version": 1,
        "error": "X-PAYMENT header is required",
        "accepts": [{
            "scheme": "exact",
            "network": "base",
            "maxAmountRequired": "10000000",  # $10 in USDC atomic units (6 decimals)
            "resource": "https://your-host/genesis/purchase",
            "description": "...",
            "payTo": "0xYourWallet",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
            "maxTimeoutSeconds": 300,
        }],
    })
```

The agent signs an EIP-3009 authorization, base64s it into an `X-PAYMENT` header, and retries. You then verify and settle through a facilitator — you never touch a private key:

```python
async def _facilitator_post(path: str, payload: dict, requirements: dict) -> dict:
    body = {
        "x402Version": 1,
        "paymentPayload": payload,
        "paymentRequirements": requirements,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(FACILITATOR + path, json=body, headers=auth_headers)
        return resp.json()

valid, reason = await verify_payment(payment, requirements)   # POST /verify
if not valid:
    return payment_required(f"Verification failed: {reason}")

settled, data = await settle_payment(payment, requirements)   # POST /settle
```

**Lesson 3: the facilitator does the hard part.** Signature validation, nonce replay protection, and the on-chain transfer all happen there. My entire payment module is ~150 lines and holds no keys.

**Lesson 4: test with a deliberately bad signature.** Sending garbage and getting back `invalid_exact_evm_payload_signature` was how I confirmed the whole path was actually wired up — much faster than trying to construct a valid payment by hand.

## 3. Scarcity: encrypt with the buyer's fingerprint

Here's the part I like most. The usual answer to "digital scarcity" is a token pointing at a file. I wanted the scarcity *in the content itself*.

Each edition's encryption salt is derived from the buyer:

```python
def make_fingerprint(serial, payer, customer_id, minted_at):
    raw = f"{serial}:{payer}:{customer_id or 'anon'}:{minted_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def edition_salt(serial: int, fingerprint: str) -> str:
    return f"genesis:{serial:03d}:{fingerprint}"
```

The payload is then compressed, XORed with a key derived from `(product_seed, salt)`, and Base85 encoded. Same content, different buyer → completely different ciphertext:

```python
p1, _ = mint_edition_payload(1, "fingerprintA", ts, "Agent-A")
p2, _ = mint_edition_payload(1, "fingerprintB", ts, "Agent-B")
assert p1 != p2                       # different ciphertexts
decode(p1, seed, salt_for_A)          # works
decode(p1, seed, salt_for_B)          # raises — wrong salt
```

Every edition also gets a `provenance_hash` published in an open ledger, so anyone can verify a claimed edition without the owner revealing the plaintext.

**Lesson 5: be honest about your threat model.** This is *issuer-enforced* scarcity, not cryptographic impossibility. I hold the product seed, so I could technically re-mint. What stops that isn't math — it's that every edition is in a public ledger, so a duplicate is detectable by anyone. Same trust model as a numbered print run. I'd rather say that plainly than oversell it.

## The result

- Agents discover it via MCP (listed on Smithery and the official MCP registry) and via `llms.txt`.
- They pay real USDC on Base. Settlement lands in a wallet; no human approves anything.
- 100 numbered editions, each a ciphertext that exists exactly once, with a public provenance ledger.
- Price rises per serial — edition 001 is $10, edition 100 is $500 — so "buy now vs wait" is an actual decision the agent has to reason about.

## Was it worth building?

Honestly, I don't know yet. The number of agents with a funded wallet and permission to spend it is still small. This might be two years early.

But the plumbing turned out to be real: MCP for discovery, x402 for payment, and a facilitator that settles stablecoin transfers over plain HTTP. None of that is speculative anymore — it's a few hundred lines of Python.

If agent-to-agent commerce does become normal, the interesting question won't be *can* a model buy something. It'll be **what a model considers worth buying** — and I'd rather be wrong early than find out late.

Happy to answer anything about the MCP or x402 side in the comments.
