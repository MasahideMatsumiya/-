#!/usr/bin/env python3
"""
出荷票PDF → 発送管理表 自動入力スクリプト

使い方:
  1. pdfs/ フォルダにその日の出荷票PDFを入れる
  2. python3 update_shipping.py を実行
"""
from __future__ import annotations

import os
import re
import base64
import glob
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ── 設定 ──────────────────────────────────────────────
SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID_SHIPPING", "18LnySuVy4-soHDxCeyh97WpeFaJqvZT4Aci0itZtRCw")
CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
PDF_FOLDER       = os.getenv("PDF_FOLDER", "./pdfs")
SHEET_NAME       = "シート1"

SIZE_TO_COL = {
    "CP":  3,   # C列: クリックポスト
    "60":  6,   # F列: 新A式60
    "80":  9,   # I列: 新A式80
    "100": 10,  # J列: 100サイズ
}
PREFECTURE_COL = 12  # L列

PREFS = (
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
)
PREF_PATTERN = re.compile("|".join(PREFS))

VISION_PROMPT = """\
この出荷票の画像を見てください。

「配送サイズ」の行に CP / 60 / 80 / 100 という4つの選択肢があります。
そのうち1つだけが黒い太枠または黒い背景でハイライトされています。

CP、60、80、100 のどれが選択されていますか？
選択されているサイズだけを1語で答えてください（例: 60）。
"""


# ── テキスト抽出（注文番号・都道府県） ────────────────
def extract_from_text(page) -> dict:
    text = page.extract_text() or ""

    m = re.search(r"注文番号\s+(\d+)", text)
    order_number = m.group(1) if m else ""
    if not order_number:
        m = re.search(r"^\s*(\d{4,5})\b", text, re.MULTILINE)
        order_number = m.group(1) if m else ""

    m = PREF_PATTERN.search(text)
    prefecture = m.group(0) if m else ""

    return {"order_number": order_number, "prefecture": prefecture}


# ── Claude Vision でサイズ検出 ────────────────────────
def detect_size_via_vision(pdf_path: str, page_num: int) -> str:
    doc = fitz.open(pdf_path)
    pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(2, 2))
    img_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
    doc.close()

    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )

    answer = response.content[0].text.strip()
    for size in ("100", "80", "60", "CP"):
        if size in answer:
            return size
    return ""


# ── メイン PDF 解析 ───────────────────────────────────
def extract_orders_from_pdf(pdf_path: str) -> list[dict]:
    results = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            info = extract_from_text(page)
            if not info["order_number"]:
                continue

            size = detect_size_via_vision(pdf_path, i)
            if size:
                print(f"  [Vision] 注文 {info['order_number']}: サイズ={size}  {info['prefecture']}")
                info["shipping_size"] = size
                results.append(info)
            else:
                print(f"  ⚠  注文 {info['order_number']}: サイズ検出失敗")

    return results


# ── Google Sheets 更新 ────────────────────────────────
def append_orders_to_sheet(gc: gspread.Client, orders: list[dict]):
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    existing = ws.col_values(1)

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

        row = [""] * 12
        row[0] = order_num
        col = SIZE_TO_COL.get(size)
        if col:
            row[col - 1] = 1
        else:
            print(f"  ⚠  注文 {order_num}: サイズ '{size}' 不明")
        row[PREFECTURE_COL - 1] = pref

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
