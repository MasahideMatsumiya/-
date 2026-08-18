# Buddy-Buddy 発送自動化ツール — エージェント引き継ぎガイド

## プロジェクト概要

Shopify ペットフードストア（Buddy-Buddy）の日次業務自動化スクリプト群。
出荷票 PDF を読み取り、2 つの Google スプレッドシートに自動入力する。

- **在庫管理表**: 商品ごとの販売数・顧客名・袋数を日付行に追記
- **発送管理表**: 注文番号・配送サイズ・都道府県を新規行に追加

---

## ファイル構成

```
buddy-buddy-tools/
├── update.py            # 在庫管理表 自動入力
├── update_shipping.py   # 発送管理表 自動入力
├── run_update.command   # Stream Deck ワンクリック実行スクリプト（macOS）
├── requirements.txt     # Python 依存パッケージ
├── .env                 # 環境変数（Git 管理外）
├── .env.example         # .env のテンプレート
├── credentials.json     # Google サービスアカウント認証（Git 管理外）
└── pdfs/                # 処理対象 PDF を置くフォルダ（Git 管理外）
```

---

## セットアップ

### 必要なもの
- Python 3.9+
- `pip3 install -r requirements.txt`

### .env（必須）
```
CLAUDE_API_KEY=sk-ant-...
SPREADSHEET_ID=17S643Uvg1V91ILIV2dvNVoavja7WE0PHmFZIFabH8FA
SPREADSHEET_ID_SHIPPING=18LnySuVy4-soHDxCeyh97WpeFaJqvZT4Aci0itZtRCw
CREDENTIALS_FILE=credentials.json
PDF_FOLDER=./pdfs
```

### credentials.json
Google Cloud サービスアカウントの JSON キーファイル。
サービスアカウント: `sheets-updater@organic-reef-467710-d2.iam.gserviceaccount.com`
両スプレッドシートの編集権限を付与済み。

---

## 実行方法

```bash
cd ~/buddy-buddy-tools
python3 update.py          # 在庫管理表のみ
python3 update_shipping.py # 発送管理表のみ
./run_update.command       # 両方まとめて実行（Stream Deck から呼び出し）
```

PDFを `pdfs/` フォルダに入れてから実行する。

---

## update.py — 在庫管理表

### 動作フロー
1. `pdfs/` 内の PDF をすべて読み込む
2. ファイル名から日付を解析（例: `4.6.001.pdf` → `2026/04/06`）
3. Claude API（haiku）で各 PDF から注文情報を JSON 抽出
4. 商品キーごとにシートを特定し、日付行に **足し算で** 販売数と備考を書き込む

### 重要: 既存値への追記
同じ日に複数回実行しても上書きされない。既存の C 列（販売数）と備考列を読んで加算する。

### 商品マッピング（PRODUCT_TO_SHEET）
```python
PRODUCT_TO_SHEET = {
    "チキン(ドライ)":     ("BBチキン【本社】在庫数",          10),  # J列
    "ベニソン":           ("BBベニソン【本社】在庫数",         9),
    "ポーク(ドライ)":     ("BBポーク【本社】在庫数",           9),
    "モリンガミルク":     ("モリンガミルク",                   9),
    "wetチキン":          ("wetチキン在庫数2023.9",            9),
    "wetホース":          ("wetホース在庫数",                  9),
    "wetポーク":          ("wetポーク在庫数",                  9),
    "トリーツ高野豆腐":   ("BBトリーツ【高野豆腐】",           9),
    "トリーツいちご":     ("BBトリーツ【いちご＆ヤギミルク】", 9),
    "トリーツ乳酸菌":     ("BBトリーツ【乳酸菌ボーロ】",       9),
    "トリーツきびなご":   ("BBトリーツ【きびなご】",           9),
    "ツヤット":           ("ツヤット",                         9),
}
```
タプルは `(シートタブ名, 備考列番号)`。BBチキンのみ J 列（10）、他は I 列（9）。

### シート構造
- A 列: 日付（`YYYY/MM/DD` 形式）
- C 列: 販売数（数値）
- I 列（9）または J 列（10）: 備考（例: `田中さま3袋、山田さま2袋、`）

### 新商品の追加手順
1. `PRODUCT_TO_SHEET` に `"キー名": ("シートタブ名", 列番号)` を追加
2. `EXTRACT_PROMPT` のリストに `"キー名 … PDF上の表記"` を追加

---

## update_shipping.py — 発送管理表

### 動作フロー
1. `pdfs/` 内の PDF をすべて読み込む
2. pdfplumber でテキスト抽出（注文番号・都道府県）
3. PyMuPDF（fitz）でページを PNG 画像に変換（2x 解像度）
4. Claude Vision API（sonnet）に画像を送り、配送サイズ（CP/60/80/100）を視覚的に判定
5. 重複チェック後、発送管理表に新規行を追加

### 重要: サイズ検出方式
PDF 内の矩形はすべて linewidth=0 のため、pdfplumber のジオメトリ解析は使えない。
PyMuPDF でページを画像化し、Claude Vision に「黒枠で囲まれているサイズ」を聞く方式。

### 列マッピング（SIZE_TO_COL）
```python
SIZE_TO_COL = {
    "CP":  3,   # C列: クリックポスト
    "60":  6,   # F列: 新A式60
    "80":  9,   # I列: 新A式80
    "100": 10,  # J列: 100サイズ
}
PREFECTURE_COL = 12  # L列: 都道府県
```

### シート構造（発送管理表 シート1）
- A 列: 注文番号（重複スキップ判定用）
- C/F/I/J 列: 配送サイズ（1 を入力）
- L 列: 都道府県

---

## PDF ファイル命名規則

```
M.D.NNN.pdf
例: 4.6.001.pdf  → 2026年4月6日の1枚目
    4.21.003.pdf → 2026年4月21日の3枚目
```

1 PDF に複数ページ（複数注文）が含まれる場合もある。

---

## 使用 API・サービス

| サービス | 用途 | モデル |
|---------|------|-------|
| Anthropic Claude API | 在庫: PDF テキスト抽出 | claude-haiku-4-5-20251001 |
| Anthropic Claude API | 発送: 配送サイズ視覚判定 | claude-sonnet-4-6 |
| Google Sheets API | スプレッドシート読み書き | gspread v6 |

---

## よくある問題

| 症状 | 原因 | 対処 |
|------|------|------|
| `ModuleNotFoundError` | pip install 未実施 | `pip3 install -r requirements.txt` |
| シートが見つからない（スキップ） | タブ名の不一致 | PRODUCT_TO_SHEET のタブ名を確認 |
| 日付行が見つからない（スキップ） | シートに該当日付の行なし | スプレッドシートに日付行を追加 |
| サイズ検出失敗 | Claude Vision が空回答 | ターミナルのエラーログを確認 |
| `git pull` で上書きエラー | ローカルに手動変更あり | `git checkout <file> && git pull` |
