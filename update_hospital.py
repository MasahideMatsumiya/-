#!/usr/bin/env python3
"""
Shopify 顧客/注文PDF → 動物病院売上票 自動入力スクリプト

使い方:
  1. Shopify の顧客ページでタグ「病院」等で絞り込み、注文詳細を PDF にする
  2. pdfs/ フォルダに PDF を入れる
  3. python3 update_hospital.py を実行

※ Buddy-Buddy の update.py / update_shipping.py と同じ構造。
"""
from __future__ import annotations

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
SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID_HOSPITAL", "1XaLdUELAPoH-ru_joS4sNx7OKgxlprniZr_mAJAtkQM")
CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
PDF_FOLDER       = os.getenv("PDF_FOLDER", "./pdfs")

# クーポンコード → 病院名（画像から判明している分のみ。実PDFで追加する）
COUPON_TO_HOSPITAL = {
    "40217": "CHICOどうぶつ診療所",
}

# 動物病院売上票の行レイアウト（1月ブロックあたりの相対行番号）
# 実PDF確認後に微調整。画像観察ベースの現状値。
ROW_OFFSETS = {
    "該当月":    1,
    "名前":      2,
    "愛犬①":    3,
    "愛犬②":    4,
    "愛犬③":    5,
    "受注日":    6,
    "注文番号":  7,
    "商品":      8,   # 商品は複数行（8〜14）に渡る可能性あり
    "クーポン名": 15,
    "合計金額税抜": 16,
    "30%":       17,
}

# 月ブロックの開始行（画像から判定: 1, 19, 38, 57, ...）
# 各ブロック 18行 + ヘッダ1行 = 19行間隔
BLOCK_HEIGHT = 19

# 顧客列ペア（B+C, D+E, F+G, ...）
# 各顧客は「データ列」と「数量列」の2列を占有
FIRST_DATA_COL = 2  # B列
COLS_PER_CUSTOMER = 2

# ── 抽出プロンプト ────────────────────────────────────
EXTRACT_PROMPT = """\
この Shopify の注文PDFから、病院キックバック集計に必要な情報を抽出してください。
以下のJSON形式のみを返してください（説明文・マークダウン不要）:

{
  "orders": [
    {
      "order_number": "1718",
      "order_date": "2025-09-25",
      "customer_name": "谷 麻美",
      "pets": ["マロンくん", "メルちゃん"],
      "items": [
        {"product": "【毎月】ポーク", "quantity": 4}
      ],
      "coupon_code": "40217",
      "subtotal_ex_tax": 10309
    }
  ]
}

注意:
- order_date は YYYY-MM-DD
- customer_name は姓名（例「谷 麻美」）
- pets は愛犬名の配列（いない場合は []）
- coupon_code は Shopify のディスカウントコード（例 40217）
- subtotal_ex_tax は税抜の合計金額（円、整数）
- 1PDFに複数注文がある場合は orders 配列に複数入れてよい
- 同月に同じ顧客が2回買っている場合も、別注文として別要素にする
"""


# ── PDF 解析 ──────────────────────────────────────────
def extract_orders_from_pdf(pdf_path: str) -> list[dict]:
    """Claude API で Shopify 注文PDF から情報を抽出して返す"""
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
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


# ── シート名の決定 ────────────────────────────────────
def sheet_name_for_coupon(coupon_code: str) -> str:
    """クーポンコードから病院シート名を決める（現状は全病院共通で1シート想定）"""
    # 画像では全病院が同じシート内の別ブロックとして並んでいる
    # 病院別にシートが分かれている場合はここで切り替える
    return "シート1"


# ── 月ブロックの開始行を探す ──────────────────────────
def find_block_start_row(ws: gspread.Worksheet, year_month: str, coupon_code: str) -> int | None:
    """
    'YYYY.M' 形式の該当月 + クーポンコードを含むブロックの開始行を返す。
    画像の例: 1行目「該当月 2025.8」+ P列に病院情報、19行目「クーポンコード: 40217. CHICOどうぶつ診療所」...
    """
    col_a = ws.col_values(1)  # A列（ラベル列）
    # 「該当月」と書かれた行を全て探す
    candidate_rows = [i + 1 for i, v in enumerate(col_a) if v == "該当月"]

    for row in candidate_rows:
        # その行の B 列が year_month と一致するか確認
        b_val = ws.cell(row, 2).value or ""
        if year_month in b_val:
            # さらに直上行のクーポンコードも確認（最初のブロックはクーポン行が無い可能性あり）
            if row > 1:
                prev = ws.cell(row - 1, 1).value or ""
                if coupon_code and coupon_code not in prev:
                    continue
            return row
    return None


# ── 空いている顧客列を探す ────────────────────────────
def find_empty_customer_col(ws: gspread.Worksheet, block_start_row: int) -> int:
    """指定ブロックの「名前」行で、値が空の最初のデータ列を返す（1-indexed）"""
    name_row = block_start_row + ROW_OFFSETS["名前"] - 1
    row_values = ws.row_values(name_row)
    col = FIRST_DATA_COL
    while col - 1 < len(row_values) and row_values[col - 1]:
        col += COLS_PER_CUSTOMER
    return col


# ── Google Sheets 書込 ────────────────────────────────
def write_order_to_sheet(ws: gspread.Worksheet, block_start_row: int, data_col: int, order: dict):
    """1注文を動物病院売上票の1顧客列ペアに書き込む"""
    qty_col = data_col + 1
    year_month = order["order_date"][:7].replace("-", ".")  # 2025-09-25 → 2025.09 → 2025.9 表記に合わせる
    # 先頭ゼロ除去（09→9）
    y, m = year_month.split(".")
    year_month = f"{y}.{int(m)}"

    updates = [
        (block_start_row + ROW_OFFSETS["該当月"] - 1, data_col, year_month),
        (block_start_row + ROW_OFFSETS["名前"] - 1,   data_col, order["customer_name"]),
        (block_start_row + ROW_OFFSETS["受注日"] - 1, data_col, f"{order['order_date'].replace('-', '年', 1).replace('-', '月')}日"),
        (block_start_row + ROW_OFFSETS["注文番号"] - 1, data_col, order["order_number"]),
        (block_start_row + ROW_OFFSETS["合計金額税抜"] - 1, data_col, order["subtotal_ex_tax"]),
    ]

    # 愛犬名
    for i, pet in enumerate(order.get("pets", [])[:3]):
        label = ["愛犬①", "愛犬②", "愛犬③"][i]
        updates.append((block_start_row + ROW_OFFSETS[label] - 1, data_col, pet))

    # 商品と数量（最大7行）
    for i, item in enumerate(order.get("items", [])[:7]):
        product_row = block_start_row + ROW_OFFSETS["商品"] - 1 + i
        updates.append((product_row, data_col, item["product"]))
        updates.append((product_row, qty_col, item["quantity"]))

    for row, col, value in updates:
        ws.update_cell(row, col, value)

    print(f"  OK  {order['customer_name']} / 注文{order['order_number']}  →  row={block_start_row}, col={data_col}")


# ── メイン ────────────────────────────────────────────
def main():
    print("=== 動物病院売上票 自動入力 ===\n")

    pdf_files = sorted(glob.glob(os.path.join(PDF_FOLDER, "*.pdf")))
    if not pdf_files:
        print(f"ERROR: {PDF_FOLDER} にPDFファイルがありません")
        return

    print(f"PDFファイル {len(pdf_files)} 件を処理します")

    all_orders: list[dict] = []
    for pdf_path in pdf_files:
        fname = Path(pdf_path).name
        print(f"\n[解析] {fname}")
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

    # Google Sheets 接続
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(SPREADSHEET_ID)

    print(f"\n[スプレッドシート書込]")
    for order in all_orders:
        coupon = str(order.get("coupon_code", "")).strip()
        hospital = COUPON_TO_HOSPITAL.get(coupon, "(不明な病院)")
        y_m = order["order_date"][:7].replace("-", ".")
        y, m = y_m.split(".")
        year_month = f"{y}.{int(m)}"

        ws = sh.worksheet(sheet_name_for_coupon(coupon))
        block_row = find_block_start_row(ws, year_month, coupon)
        if block_row is None:
            print(f"  ⚠  {year_month} / クーポン{coupon} のブロックが見つかりません（スキップ）")
            continue

        data_col = find_empty_customer_col(ws, block_row)
        write_order_to_sheet(ws, block_row, data_col, order)

    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
