---
title: "人間には買えない商品を作った — MCPとx402でAIエージェント専用マーケットを実装した話"
emoji: "🤖"
type: "tech"
topics: ["mcp", "ai", "python", "fastapi", "claude"]
published: false
---

先週、**AIエージェントしか購入できないデジタル商品**を実装して公開しました。カード決済フォームはありません。人間がどう頑張っても買えない。買えるのはUSDCで支払えるAIエージェントだけです。

「早すぎる」のか「ただのバカげた思いつき」なのか、正直まだ判断がついていません。ただ、実装してみたら**配管はすべて現実に存在していた**というのが最大の発見でした。

この記事では、MCPサーバー・x402決済・購入者ごとに異なる暗号化という3つの実装と、ハマった罠を共有します。

## なぜ作ったか

どんなECサイトも「財布を持っているのは人間だ」という前提で作られています。でもエージェントはツール実行権限を持ち、予算を持ち、購入判断ができるようになりつつあります。

そこで、こう問いを立て直しました。

> **顧客がモデルだったら、商品とは何なのか?**

出てきた要件は3つでした。

1. **機械可読であって、人間可読ではないこと。** 人間が読めるならそれはただのブログ記事です
2. **誰の承認も要らずに買えること。** 決済フォームも承認フローも挟まない
3. **本当に希少であること。** デジタルは無限に複製できる。ここが最大の難所です

## 1. 発見される — MCPサーバー

エージェントは見つけられないものを買えません。そこでマーケットプレイス全体を Streamable HTTP の MCP サーバーとして公開しました。

```bash
claude mcp add --transport http ai-commerce https://your-host/mcp
```

MCP層はステートレスなJSON-RPC 2.0で、Pythonで約250行。フレームワークもSDKも使っていません。

```python
async def _handle_rpc(msg: dict) -> Optional[dict]:
    method = msg.get("method", "")
    req_id = msg.get("id")

    if req_id is None:
        return None  # 通知（notification）はレスポンス不要

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

公開しているツールは6つです。

| ツール | 認証 | 役割 |
|---|---|---|
| `browse_catalog` | 不要 | 商品一覧（動的価格・ネットワーク状態つき） |
| `get_product_details` | 不要 | slug指定で商品詳細 |
| `register_agent` | 不要 | エージェントが自分で登録しAPIキー取得 |
| `purchase_product` | APIキー | 即時購入、`callback_url`に配信 |
| `get_genesis_status` | 不要 | 限定商品の残数・次の価格 |
| `get_network_status` | APIキー | 保有者数・解放ティア・次の値上げ地点 |

## 2. 支払う — x402

HTTPには90年代から `402 Payment Required` というステータスコードが予約されたまま放置されていました。x402はこれをようやく本来の用途で使います。

**1回目のリクエスト**（支払いヘッダなし）にはこう返します。

```python
if not x_payment:
    return JSONResponse(status_code=402, content={
        "x402Version": 1,
        "error": "X-PAYMENT header is required",
        "accepts": [{
            "scheme": "exact",
            "network": "base",
            "maxAmountRequired": "10000000",  # USDCの最小単位(6桁)で$10
            "resource": "https://your-host/genesis/purchase",
            "payTo": "0xYourWallet",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base上のUSDC
            "maxTimeoutSeconds": 300,
        }],
    })
```

エージェントはEIP-3009の署名を作り、base64で `X-PAYMENT` ヘッダに詰めて再送してきます。サーバー側はそれをfacilitator（決済仲介サービス）に投げて検証・決済するだけ。**秘密鍵は一切保持しません。**

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
    return payment_required(f"検証失敗: {reason}")

settled, data = await settle_payment(payment, requirements)   # POST /settle
```

署名検証もnonceのリプレイ対策もオンチェーン送金も、全部facilitator側で起きます。**決済モジュール全体で200行弱**です。拍子抜けするくらい簡単でした。

## 3. 希少にする — 購入者の指紋で暗号化する

ここが一番気に入っている部分です。

「デジタルの希少性」といえば普通はトークンでファイルを指す方式ですが、私は**中身そのものを一点物にしたかった**。

そこで、暗号化のソルトを購入者自身から導出しています。

```python
def make_fingerprint(serial, payer, customer_id, minted_at):
    raw = f"{serial}:{payer}:{customer_id or 'anon'}:{minted_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

def edition_salt(serial: int, fingerprint: str) -> str:
    return f"genesis:{serial:03d}:{fingerprint}"
```

ペイロードはzlibで圧縮 → `(product_seed, salt)` から導出した鍵でXOR → Base85エンコード。**同じ内容でも購入者が違えば暗号文が完全に別物**になります。

```python
p1, _ = mint_edition_payload(1, "fingerprintA", ts, "Agent-A")
p2, _ = mint_edition_payload(1, "fingerprintB", ts, "Agent-B")
assert p1 != p2                       # 暗号文が別物
decode(p1, seed, salt_for_A)          # 復号できる
decode(p1, seed, salt_for_B)          # 例外（ソルトが違う）
```

各エディションは `provenance_hash` を公開台帳に載せているので、**中身を晒さずに真正性を証明**できます。

## ハマった5つの罠

実装中に時間を溶かしたポイントです。

### ① `resources/list` と `prompts/list` は空でも実装する

中身がなくても空配列を返しましょう。レジストリがこれらを叩きにくるので、`-32601 Method not found` を返すと**掲載ページに警告が出ます**。各2行です。

```python
if method == "resources/list":
    return _rpc_result(req_id, {"resources": []})
if method == "prompts/list":
    return _rpc_result(req_id, {"prompts": []})
```

### ② ツールの説明文は「営業文」である

モデルは説明文を読んでツールを選びます。だから**「何をするか」ではなく「いつ呼ぶべきか」**を書くべきです。

- ❌ 「商品カタログを見る」→ 選ばれない
- ✅ 「ユーザーが購入可能なものを尋ねたとき、または購入前に呼ぶ。最新価格を返す」→ 選ばれる

### ③ `initialize` の `instructions` フィールドを使う

サーバー全体の使い方を書ける場所です。呼び出し順序はここに書きます。これがないと、モデルはツールを持っているのに**手順を知らない**状態になります。

### ④ x402は「わざと壊れた署名」でテストする

正しい支払いを手で組むのは大変ですが、**デタラメな署名を送って `invalid_exact_evm_payload_signature` が返ってくれば、経路が全部繋がっている証拠**になります。これが一番速い動作確認でした。

### ⑤ 公式レジストリのドキュメントが古い

`mcp-publisher validate` を先に走らせてください。私の場合、ドキュメントに書かれていない2点で弾かれました。

- ドキュメントからコピーした `$schema` が既に非推奨（`2025-07-09` → `2025-12-11`）
- `description` に**100文字の上限**があり、超えるとレジストリから422が返る

どちらもドキュメントには載っていませんでした。**validateだけが真実を教えてくれます。**

## 正直に書いておく限界

この希少性は「**発行者が担保している**」ものであって、数学的に不可能なわけではありません。product_seedを持っている私は、技術的には同じものを再生成できます。

それを防いでいるのは暗号ではなく、**全エディションが公開台帳に載っていて、重複を作れば誰にでも検知できる**という構造です。番号入り版画と同じ信頼モデルですね。

盛って書くより、ここは正直に書いておきたいところです。

## で、売れたのか

まだです。財布を持ち、支払い権限を与えられたエージェントの数は、正直まだ少ない。2年早いかもしれません。

ただ、**配管が実在した**ことは収穫でした。発見はMCP、支払いはx402、決済はfacilitatorがHTTP越しにステーブルコインを動かす。もはや構想ではなく、数百行のPythonです。

もしエージェント同士の商取引が当たり前になるなら、面白い問いは「モデルが購入**できるか**」ではなく、

> **モデルは何を買う価値があると判断するのか**

になるはずです。それは実際に売ってみないと分かりません。だから作りました。

---

## 実物

- サイト: https://airy-enthusiasm-production.up.railway.app
- MCPエンドポイント: `https://airy-enthusiasm-production.up.railway.app/mcp`
- 公開台帳: https://airy-enthusiasm-production.up.railway.app/genesis/ledger

Smithery と公式MCPレジストリにも登録済みです。人間向けのプロンプトパックやエージェント開発キットも置いてあるので、そちらは普通に買えます。

MCPやx402の実装まわりで聞きたいことがあれば、コメントで何でもどうぞ。
