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
import json
import base64
import glob
from pathlib import Path

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

# Claude fallback 用プロンプト（geometry 失敗時のみ使用）
FALLBACK_PROMPT = """\
この出荷票PDFから配送情報を抽出してください。

以下のJSON形式のみを返してください：
{
  "orders": [
    {
      "order_number": "2622",
      "shipping_size": "60",
      "prefecture": "栃木県"
    }
  ]
}

「配送サイズ」欄の CP・60・80・100 のうち、
太い黒枠で囲まれているものが選択済みサイズです。
BC/BP/BV の後ろの数字（袋数）は配送サイズと無関係です。

prefecture：都道府県名のみ
order_number：注文番号の数字のみ
"""


# ── pdfplumber で配送サイズを取得 ─────────────────────
def detect_size_from_geometry(page) -> str | None:
    """
    黒塗り矩形（fill≈0）のx範囲内に含まれる最右のサイズラベルを返す。
    選択されたサイズはCPから選択サイズまでを覆う黒矩形で示される。
    """
    words = page.extract_words()
    rects = page.rects

    size_labels: dict[str, tuple[float, float]] = {}
    for w in words:
        if w["text"] in ("CP", "60", "80", "100"):
            cx = (w["x0"] + w["x1"]) / 2
            cy = (w["top"] + w["bottom"]) / 2
            size_labels[w["text"]] = (cx, cy)

    if len(size_labels) < 2:
        return None

    label_y = sum(cy for _, cy in size_labels.values()) / len(size_labels)

    # 黒塗り矩形（fill < 0.3）をサイズ行付近（±80px）から探す
    dark_rects = []
    for r in rects:
        fill = r.get("non_stroking_color")
        if fill is None:
            continue
        is_dark = (
            (isinstance(fill, (int, float)) and fill < 0.3) or
            (isinstance(fill, (list, tuple)) and len(fill) >= 3
             and all(v < 0.3 for v in fill[:3]))
        )
        if not is_dark:
            continue
        rect_cy = (r["top"] + r["bottom"]) / 2
        if abs(rect_cy - label_y) > 80:
            continue
        dark_rects.append(r)

    if not dark_rects:
        return None

    # 黒矩形のx範囲内に含まれるサイズラベルのうち最も右のものを返す
    candidates: list[tuple[float, str]] = []
    for size, (cx, cy) in size_labels.items():
        for r in dark_rects:
            if r["x0"] <= cx <= r["x1"]:
                candidates.append((cx, size))
                break

    if not candidates:
        return None

    return max(candidates, key=lambda t: t[0])[1]


# ── pdfplumber でテキスト情報を取得 ───────────────────
def extract_from_text(page) -> dict:
    """注文番号・都道府県をテキストから抽出"""
    text = page.extract_text() or ""

    # 注文番号：「注文番号 XXXX」または先頭の4〜5桁数字
    m = re.search(r"注文番号\s+(\d+)", text)
    order_number = m.group(1) if m else ""
    if not order_number:
        m = re.search(r"^\s*(\d{4,5})\b", text, re.MULTILINE)
        order_number = m.group(1) if m else ""

    # 都道府県
    m = PREF_PATTERN.search(text)
    prefecture = m.group(0) if m else ""

    return {"order_number": order_number, "prefecture": prefecture}


# ── Claude fallback（geometry 失敗時のみ） ────────────
def extract_via_claude(pdf_path: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    with open(pdf_path, "rb") as f:
        pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document",
                 "source": {"type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64}},
                {"type": "text", "text": FALLBACK_PROMPT},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip()).get("orders", [])


# ── メイン PDF 解析 ───────────────────────────────────
def extract_orders_from_pdf(pdf_path: str) -> list[dict]:
    results = []
    needs_claude = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            info = extract_from_text(page)
            if not info["order_number"]:
                continue

            size = detect_size_from_geometry(page)
            if size:
                print(f"  [geometry] サイズ検出: {size}")
                info["shipping_size"] = size
                results.append(info)
            else:
                print(f"  [geometry] 検出失敗")
                needs_claude = True

    if needs_claude:
        print(f"  → Claude API にフォールバック")
        try:
            claude_orders = extract_via_claude(pdf_path)
            found_nums = {o["order_number"] for o in results}
            for o in claude_orders:
                if o.get("order_number") not in found_nums:
                    results.append(o)
        except Exception as e:
            print(f"  ERROR (Claude fallback): {e}")

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
