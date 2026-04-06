#!/usr/bin/env python3
"""
出荷票PDF → Google Sheets 在庫管理表 自動更新スクリプト

使い方:
  1. pdfs/ フォルダにその日の出荷票PDFを入れる
  2. python3 update.py を実行
"""
import os
import json
import base64
import glob
from datetime import date
from pathlib import Path

import anthropic
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ── 設定 ──────────────────────────────────────────────
SPREADSHEET_ID  = os.getenv("SPREADSHEET_ID", "17S643Uvg1V91ILIV2dvNVoavja7WE0PHmFZIFabH8FA")
CLAUDE_API_KEY  = os.getenv("CLAUDE_API_KEY")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
PDF_FOLDER      = os.getenv("PDF_FOLDER", "./pdfs")

# Shopify 商品名キー → スプレッドシートのシートタブ名
PRODUCT_TO_SHEET = {
    "チキン(ドライ)":     "BBチキン【本社】在庫数",
    "ベニソン":           "BBベニソン【本社】在庫数",
    "ポーク(ドライ)":     "BBポーク【本社】在庫数",
    "モリンガミルク":     "モリンガミルク",
    "wetチキン":          "wetチキン在庫数2023.9",
    "wetホース":          "wetホース在庫数",
    "wetポーク":          "wetポーク在庫数",
    "トリーツ高野豆腐":   "BBトリーツ【高野豆腐】",
    "トリーツいちご":     "BBトリーツ【いちご＆ヤギミルク】",
    "トリーツ乳酸菌":     "BBトリーツ【乳酸菌ボーロ】",
    "ツヤット":           "ツヤット",
}

EXTRACT_PROMPT = """\
この出荷票PDFから注文情報を抽出してください。

以下のJSON形式のみを返してください（説明文・マークダウン不要）：
{
  "orders": [
    {
      "customer_name": "堀江",
      "product_key": "チキン(ドライ)",
      "quantity": 4
    }
  ]
}

product_key は以下から最も近いものを選んでください：
- チキン(ドライ)   … BBドライフード チキン（定期便・都度購入どちらも）
- ベニソン         … BBドライフード ベニソン
- ポーク(ドライ)   … BBドライフード ポーク（定期便・都度購入どちらも）
- モリンガミルク   … モリンガミルク
- wetチキン        … ウェットフード チキン
- wetホース        … ウェットフード ホース
- wetポーク        … ウェットフード ポーク
- トリーツ高野豆腐 … BBトリーツ 高野豆腐
- トリーツいちご   … BBトリーツ いちご＆ヤギミルク
- トリーツ乳酸菌   … BBトリーツ 乳酸菌ボーロ
- ツヤット         … ツヤット

customer_name はお客様の「姓（名字）」のみにしてください。
"""

# ── PDF 解析 ──────────────────────────────────────────
def extract_orders_from_pdf(pdf_path: str) -> list[dict]:
    """Claude API で出荷票 PDF から注文情報を抽出して返す"""
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
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
    # ```json ～ ``` で囲まれていても対応
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw.strip())
    return data.get("orders", [])


# ── Google Sheets 更新 ────────────────────────────────
def update_sheet(
    gc: gspread.Client,
    spreadsheet_id: str,
    sheet_name: str,
    entries: list[dict],
    entry_date: str,
) -> bool:
    """指定シートの entry_date 行に販売数と備考を書き込む"""
    try:
        ws = gc.open_by_key(spreadsheet_id).worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        print(f"  ⚠  シート '{sheet_name}' が見つかりません（スキップ）")
        return False

    # A列の日付と一致する行を探す
    col_a = ws.col_values(1)
    try:
        row_idx = col_a.index(entry_date) + 1  # 1-indexed
    except ValueError:
        print(f"  ⚠  {entry_date} の行が '{sheet_name}' にありません（スキップ）")
        return False

    total_bags = sum(e["quantity"] for e in entries)
    biko = "".join(f"{e['customer_name']}さま{e['quantity']}袋、" for e in entries)

    ws.update_cell(row_idx, 3, total_bags)  # C列: 販売
    ws.update_cell(row_idx, 10, biko)       # J列: 備考

    print(f"  OK  {sheet_name}: {total_bags}袋  |  {biko}")
    return True


# ── メイン ────────────────────────────────────────────
def main():
    today_str = date.today().strftime("%Y/%m/%d")
    print(f"=== 在庫管理表 自動更新  {today_str} ===\n")

    # PDF ファイル確認
    pdf_files = sorted(glob.glob(os.path.join(PDF_FOLDER, "*.pdf")))
    if not pdf_files:
        print(f"ERROR: {PDF_FOLDER} にPDFファイルがありません")
        return

    print(f"PDFファイル {len(pdf_files)} 件を処理します")

    # 全 PDF から注文を収集
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

    # 商品キー別にグループ化
    groups: dict[str, list[dict]] = {}
    for order in all_orders:
        key = order.get("product_key", "")
        groups.setdefault(key, []).append(order)

    # Google Sheets に接続
    print("\n[Google Sheets 更新]")
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)

    for product_key, entries in groups.items():
        sheet_name = PRODUCT_TO_SHEET.get(product_key)
        if not sheet_name:
            print(f"  ⚠  '{product_key}' のシートマッピングが未定義（スキップ）")
            continue
        update_sheet(gc, SPREADSHEET_ID, sheet_name, entries, today_str)

    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
