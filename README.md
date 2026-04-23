# 動物病院売上票 自動入力ツール

Shopify Admin API から直接、動物病院売上票（Google スプレッドシート）へキックバック集計用のデータを自動入力するツール。

## 処理フロー

```
[Shopify Admin API (GraphQL)]
  ├─ 病院タグ付き顧客を取得 (customers?tag=CHICOどうぶつ診療所)
  ├─ 顧客メタフィールドから愛犬名を取得
  └─ 指定月の注文を取得（税抜・商品・数量）
      ↓ gspread + Google サービスアカウント
[動物病院売上票 の病院別シート / 該当月ブロック / 空列]
```

## 対応病院 / キックバック率

| 顧客タグ | キックバック率 | 書込先シート |
|---|---:|---|
| `CHICOどうぶつ診療所` | 30% | `CHICOどうぶつ診療所` |
| `viviANDOG` | 20% | `viviANDOG` |

追加するときは `update_hospital.py` の `HOSPITALS` に追記。

## 事前準備

### 1. Python 環境

```bash
pip install -r requirements.txt
```

### 2. Shopify Admin API トークン発行

1. 管理画面 → 設定 → アプリと販売チャネル → **アプリを開発**
2. 「カスタムアプリを作成」
3. Admin API アクセススコープ:
   - `read_customers`
   - `read_orders`
   - `read_customer_metafields`
4. インストール → Admin API アクセストークン（`shpat_...`）を控える

### 3. Google サービスアカウント

1. Google Cloud Console → IAM → サービスアカウント → 作成
2. JSON 鍵をダウンロード → `credentials.json` として配置
3. Google Sheets API を有効化
4. 動物病院売上票をサービスアカウントのメールに「編集者」で共有

### 4. `.env` 作成

```bash
cp .env.example .env
# エディタで値を埋める
```

## 使い方

```bash
# dry-run: Shopify 取得のみ（書込なし）で動作確認
python3 update_hospital.py --month 2026-03 --dry-run

# 本番: スプレッドシートへ書き込む
python3 update_hospital.py --month 2026-03
```

## 実環境で要調整の設定

`update_hospital.py` 冒頭:

- `PET_METAFIELD_NAMESPACE` / `PET_METAFIELD_KEY` … 愛犬名メタフィールドの namespace/key
- `PRODUCT_NAME_MAP` … Shopify 商品名 → スプレッドシート商品ドロップダウン値
- `ROW_OFFSETS` … 月ブロック内の行レイアウト
- `FIRST_DATA_COL` / `COLS_PER_CUSTOMER` … 顧客列の配置

## 備考

- 同月に同じ顧客が複数回購入した場合、**別の列として**追加（「名前」行で空の次の列を自動検出）
- シート名が `HOSPITALS` の `sheet_name` と一致しない場合はスキップ
- 該当月ブロックが見つからない場合もスキップ（事前にスプレッドシート側でブロックを作っておく前提）
