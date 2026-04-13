#!/usr/bin/env python3
"""
出荷票PDF → 発送管理表 自動入力スクリプト

使い方:
  1. pdfs/ フォルダにその日の出荷票PDFを入れる
  2. python3 update_shipping.py を実行
"""
import os
import re
import json
import base64
import glob
from pathlib import Path

import anthropic
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ── 設定 ──────────────────────────────────────────────
SPREADSHEET_ID  = os.getenv("SPREADSHEET_ID_SHIPPING", "18LnySuVy4-soHDxCeyh97WpeFaJqvZT4Aci0itZtRCw")
CLAUDE_API_KEY  = os.getenv("CLAUDE_API_KEY")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
PDF_FOLDER      = os.getenv("PDF_FOLDER", "./pdfs")
SHEET_NAME      = "シート1"

# 配送サイズ → 列番号（1-based: A=1, B=2, ...）
# A:注文番号 B:会員番号 C:クリックポスト D:60サイズ E:N式60
# F:新A式60  G:70サイズ H:80サイズ     I:新A式80  J:100サイズ
# K:食いつき L:発送先
SIZE_TO_COL = {
    "CP":  3,   # C列: クリックポスト
    "60":  6,   # F列: 新A式60
    "80":  9,   # I列: 新A式80
    "100": 10,  # J列: 100サイズ
}
PREFECTURE_COL = 12  # L列: 発送先

EXTRACT_PROMPT = """\
この出荷票PDFから配送情報を抽出してください。

以下のJSON形式のみを返してください（説明文・マークダウン不要）：
{
  "orders": [
    {
      "order_number": "2520",
      "shipping_size": "60",
      "prefecture": "神奈川県"
    }
  ]
}

【配送サイズの読み方 - 重要】
出荷票の「配送サイズ」欄に CP・60・80・100 の4つの項目が横並びになっています。
その中で「四角いボックスで囲まれているもの」だけが選択された配送サイズです。
囲まれていないものは選択されていません。

絶対に守ること：
- 商品の袋数（BC の数字）は配送サイズと無関係です。無視してください。
- 「BC 3」「BC 8」などの数字を配送サイズと混同しないでください。
- 配送サイズはあくまで「配送サイズ」欄のボックスで囲まれた数字のみです。

shipping_size：
- "CP"  … クリックポストのボックスが選択されている場合
- "60"  … 60のボックスが選択されている場合
- "80"  … 80のボックスが選択されている場合
- "100" … 100のボックスが選択されている場合

prefecture は都道府県名のみ（例：東京都、神奈川県、大阪府）
order_number は注文番号の数字のみ
"""


# ── PDF 解析 ──────────────────────────────────────────
def extract_orders_from_pdf(pdf_path: str) -> list[dict]:
    """Claude API で出荷票 PDF から配送情報を抽出して返す"""
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": EXTRACT_PROMPT},
            ],
        }],
    )

    raw = response.content[0].text.strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw.strip())
    return data.get("orders", [])


# ── Google Sheets 更新 ────────────────────────────────
def append_orders_to_sheet(gc: gspread.Client, orders: list[dict]):
    """発送管理表に注文を1行ずつ追記する"""
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

    # 重複チェック用：既存の注文番号を取得
    existing = ws.col_values(1)  # A列

    for order in orders:
        order_num = str(order.get("order_number", "")).strip()
        size      = str(order.get("shipping_size", "")).strip()
        pref      = str(order.get("prefecture", "")).strip()

        if not order_num:
            print(f"  ⚠  注文番号が空のためスキップ")
            continue

        if order_num in existing:
            print(f"  ⚠  注文 {order_num} はすでに存在します（スキップ）")
            continue

        # 12列分の空行を作成（A〜L）
        row = [""] * 12
        row[0] = order_num                       # A: 注文番号

        col = SIZE_TO_COL.get(size)
        if col:
            row[col - 1] = 1                     # 該当サイズ列: 1
        else:
            print(f"  ⚠  注文 {order_num}: 配送サイズ '{size}' が不明")

        row[PREFECTURE_COL - 1] = pref           # L: 発送先

        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"  OK  注文 {order_num}: {size}サイズ  {pref}")


# ── メイン ────────────────────────────────────────────
def main():
    print("=== 発送管理表 自動入力 ===\n")

    pdf_files = sorted(glob.glob(os.path.join(PDF_FOLDER, "*.pdf")))
    if not pdf_files:
        print(f"ERROR: {PDF_FOLDER} にPDFファイルがありません")
        return

    print(f"PDFファイル {len(pdf_files)} 件を処理します")

    all_orders: list[dict] = []
    for pdf_path in pdf_files:
        print(f"\n[解析] {Path(pdf_path).name}")
        try:
            orders = extract_orders_from_pdf(pdf_path)
            print(f"  抽出: {len(orders)} 件")
            all_orders.extend(orders)
        except json.JSONDecodeError as e:
            print(f"  ERROR: JSON parse error - {e}")
        except Exception as e:
            print(f"  ERROR: {e}")

    if not all_orders:
        print("\nERROR: 注文データを取得できませんでした")
        return

    print(f"\n[Google Sheets 追記]")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    append_orders_to_sheet(gc, all_orders)

    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
