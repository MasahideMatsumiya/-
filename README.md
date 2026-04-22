# 動物病院売上票 自動入力ツール

Shopify の注文PDFから、動物病院売上票（Google スプレッドシート）へキックバック集計用のデータを自動入力するツール。

Buddy-Buddy の `update.py` / `update_shipping.py` と同じ構造（Claude API で PDF 解析 + gspread で Sheets 書込）。

## 処理フロー

```
[Shopify]
  ↓ タグ「病院」等で絞込 → 注文詳細を PDF 出力
[pdfs/*.pdf]
  ↓ Claude API (claude-sonnet-4-6) でJSON抽出
[注文データ (JSON)]
  ↓ gspread + Google サービスアカウント
[動物病院売上票 の該当月ブロックの空列]
```

## 事前準備

1. Python 3.10+
2. 依存関係をインストール

   ```
   pip install -r requirements.txt
   ```

3. `.env` を作成（`.env.example` をコピーして値を埋める）
   - `CLAUDE_API_KEY` … https://console.anthropic.com で発行
   - `SPREADSHEET_ID_HOSPITAL` … 動物病院売上票のスプレッドシートID
   - `CREDENTIALS_FILE` … Google サービスアカウント JSON のパス

4. `credentials.json` を配置（リポジトリには含めない。`.gitignore` 済み）
   - Google Cloud Console でサービスアカウントを作成 → JSON鍵をダウンロード
   - 対象スプレッドシートをサービスアカウントのメールアドレスに「編集者」で共有

## 使い方

```bash
# 1. pdfs/ に Shopify からエクスポートした PDF を入れる
cp ~/Downloads/shopify-export.pdf pdfs/

# 2. 実行
python3 update_hospital.py
```

## 対応クーポンコード

| コード | 病院名 |
|---|---|
| 40217 | CHICOどうぶつ診療所 |

※実PDFを確認次第、`update_hospital.py` の `COUPON_TO_HOSPITAL` に追記。

## 調整が必要な箇所（実PDF受領後）

`update_hospital.py` 冒頭の以下を実サンプルで検証・調整:

- `ROW_OFFSETS` … スプレッドシートの月ブロック内の行レイアウト
- `BLOCK_HEIGHT` … 月ブロック1つあたりの行数
- `FIRST_DATA_COL` / `COLS_PER_CUSTOMER` … 顧客列の配置
- `sheet_name_for_coupon()` … 病院別にシートが分かれている場合の切替

## 備考

- 同一月に同じ顧客が複数回購入した場合は、別の列として追加されます
- すでに書き込まれている列はスキップせず、「名前」が空の次の列に追記します
