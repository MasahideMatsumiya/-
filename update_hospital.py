#!/usr/bin/env python3
"""
Shopify Admin API → 動物病院売上票 自動入力スクリプト

使い方:
  python3 update_hospital.py --month 2026-03

対象月の各病院タグ付き顧客の注文を Shopify から取得し、
病院ごとのシートの該当月ブロックに書き込む。
"""
from __future__ import annotations

import os
import json
import argparse
from calendar import monthrange

import requests
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# ── 設定 ──────────────────────────────────────────────
SHOPIFY_SHOP     = os.getenv("SHOPIFY_SHOP_DOMAIN", "buddy-buddy.myshopify.com")
SHOPIFY_TOKEN    = os.getenv("SHOPIFY_ADMIN_TOKEN")
SPREADSHEET_ID   = os.getenv("SPREADSHEET_ID_HOSPITAL")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")

API_VERSION = "2024-10"

# 病院タグ → 設定（キックバック率・書込先シート名）
HOSPITALS = {
    "CHICOどうぶつ診療所": {"kickback_rate": 0.30, "sheet_name": "CHICOどうぶつ診療所"},
    "viviANDOG":            {"kickback_rate": 0.20, "sheet_name": "viviANDOG"},
}

# 愛犬名が入っている顧客メタフィールド（実環境で namespace/key を要確認）
PET_METAFIELD_NAMESPACE = "custom"
PET_METAFIELD_KEY       = "pet_names"

# Shopify 商品名 → スプレッドシートのドロップダウン値マップ（実PDFで追記）
PRODUCT_NAME_MAP = {
    "【定期便】バディバディ腸活&口腔ケアドライフード ポーク": "【毎月】ポーク",
    "【定期便】バディバディ腸活&口腔ケアドライフード チキン": "【毎月】チキン",
    "【定期便】バディバディ腸活&口腔ケアドライフード ベニソン": "【毎月】ベニソン",
}

# 月ブロック内の相対行番号（画像観察ベース。実シートで要検証）
ROW_OFFSETS = {
    "該当月":        1,
    "名前":          2,
    "愛犬①":        3,
    "愛犬②":        4,
    "愛犬③":        5,
    "受注日":        6,
    "注文番号":      7,
    "商品":          8,   # 商品は複数行（8〜14）
    "合計金額税抜": 17,
    "キックバック": 18,
}

FIRST_DATA_COL    = 2  # B列
COLS_PER_CUSTOMER = 2  # データ列 + 数量列

# ── Shopify GraphQL クライアント ──────────────────────
def gql(query: str, variables: dict | None = None) -> dict:
    url = f"https://{SHOPIFY_SHOP}/admin/api/{API_VERSION}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_TOKEN,
        "Content-Type": "application/json",
    }
    resp = requests.post(url, json={"query": query, "variables": variables or {}}, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")
    return data["data"]


def get_customers_by_tag(tag: str) -> list[dict]:
    """指定タグの顧客を全件取得（メタフィールド含む）"""
    query = """
    query ($q: String!, $cursor: String) {
      customers(first: 50, query: $q, after: $cursor) {
        edges {
          node {
            id
            displayName
            firstName
            lastName
            metafields(first: 20) {
              edges { node { namespace key value type } }
            }
          }
          cursor
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    """
    customers: list[dict] = []
    cursor = None
    while True:
        data = gql(query, {"q": f"tag:'{tag}'", "cursor": cursor})
        edges = data["customers"]["edges"]
        customers.extend(e["node"] for e in edges)
        if not data["customers"]["pageInfo"]["hasNextPage"]:
            break
        cursor = data["customers"]["pageInfo"]["endCursor"]
    return customers


def get_orders_for_customer(customer_id: str, year: int, month: int) -> list[dict]:
    """顧客の指定月の注文を取得"""
    numeric_id = customer_id.split("/")[-1]  # gid://shopify/Customer/123 → 123
    first_day = f"{year:04d}-{month:02d}-01"
    last_day_num = monthrange(year, month)[1]
    last_day = f"{year:04d}-{month:02d}-{last_day_num:02d}"

    query = """
    query ($q: String!) {
      orders(first: 100, query: $q, sortKey: CREATED_AT) {
        edges {
          node {
            id
            name
            createdAt
            totalPriceSet    { shopMoney { amount } }
            subtotalPriceSet { shopMoney { amount } }
            totalTaxSet      { shopMoney { amount } }
            taxesIncluded
            lineItems(first: 50) {
              edges {
                node {
                  title
                  quantity
                  originalUnitPriceSet { shopMoney { amount } }
                }
              }
            }
          }
        }
      }
    }
    """
    q = f"customer_id:{numeric_id} AND created_at:>={first_day} AND created_at:<={last_day}T23:59:59"
    data = gql(query, {"q": q})
    return [e["node"] for e in data["orders"]["edges"]]


# ── 顧客メタフィールドから愛犬名 ──────────────────────
def extract_pet_names(customer: dict) -> list[str]:
    for edge in customer.get("metafields", {}).get("edges", []):
        mf = edge["node"]
        if mf["namespace"] != PET_METAFIELD_NAMESPACE or mf["key"] != PET_METAFIELD_KEY:
            continue
        value = mf["value"]
        # 値は JSON配列 / カンマ区切り / 単一文字列 のいずれか
        if value.startswith("["):
            try:
                return [str(v) for v in json.loads(value)]
            except json.JSONDecodeError:
                pass
        if "," in value or "、" in value:
            return [v.strip() for v in value.replace("、", ",").split(",") if v.strip()]
        return [value.strip()] if value.strip() else []
    return []


def compute_subtotal_ex_tax(order: dict) -> int:
    """税抜合計 = 合計 ÷ 1.1（消費税10%内税前提）"""
    total = float(order["totalPriceSet"]["shopMoney"]["amount"])
    return round(total / 1.1)


def format_product_title(title: str) -> str:
    return PRODUCT_NAME_MAP.get(title, title)


# ── スプレッドシート書込 ──────────────────────────────
def find_block_start_row(ws: gspread.Worksheet, year_month: str) -> int | None:
    """A列が「該当月」かつ B列に YYYY.M を含む行を返す"""
    col_a = ws.col_values(1)
    candidates = [i + 1 for i, v in enumerate(col_a) if v == "該当月"]
    for row in candidates:
        b_val = ws.cell(row, 2).value or ""
        if year_month in b_val:
            return row
    return None


def find_empty_customer_col(ws: gspread.Worksheet, block_start_row: int) -> int:
    """「名前」行で空の最初のデータ列（1-indexed）を返す"""
    name_row = block_start_row + ROW_OFFSETS["名前"] - 1
    row_values = ws.row_values(name_row)
    col = FIRST_DATA_COL
    while col - 1 < len(row_values) and row_values[col - 1]:
        col += COLS_PER_CUSTOMER
    return col


def a1(row: int, col: int) -> str:
    return gspread.utils.rowcol_to_a1(row, col)


def write_order_to_sheet(
    ws: gspread.Worksheet,
    block_start_row: int,
    data_col: int,
    customer_name: str,
    pets: list[str],
    order: dict,
    year_month: str,
    kickback_rate: float,
) -> None:
    qty_col = data_col + 1
    y, m, d = order["createdAt"][:10].split("-")
    date_str = f"{y}年{int(m)}月{int(d)}日"
    order_name = order["name"].lstrip("#")
    subtotal_ex_tax = compute_subtotal_ex_tax(order)
    kickback_amount = round(subtotal_ex_tax * kickback_rate)

    updates: list[dict] = []

    def add(row_offset: int, col: int, value):
        row = block_start_row + row_offset - 1
        updates.append({"range": a1(row, col), "values": [[value]]})

    add(ROW_OFFSETS["該当月"],       data_col, year_month)
    add(ROW_OFFSETS["名前"],         data_col, customer_name)
    add(ROW_OFFSETS["受注日"],       data_col, date_str)
    add(ROW_OFFSETS["注文番号"],     data_col, order_name)
    add(ROW_OFFSETS["合計金額税抜"], data_col, subtotal_ex_tax)
    add(ROW_OFFSETS["キックバック"], data_col, kickback_amount)

    for i, pet in enumerate(pets[:3]):
        label = ["愛犬①", "愛犬②", "愛犬③"][i]
        add(ROW_OFFSETS[label], data_col, pet)

    for i, edge in enumerate(order["lineItems"]["edges"][:7]):
        item = edge["node"]
        add(ROW_OFFSETS["商品"] + i, data_col, format_product_title(item["title"]))
        add(ROW_OFFSETS["商品"] + i, qty_col,  item["quantity"])

    ws.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"  OK  {customer_name} / {order['name']} / 税抜 ¥{subtotal_ex_tax:,} / KB ¥{kickback_amount:,}  (row={block_start_row}, col={data_col})")


# ── メイン ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="対象月 (例: 2026-03)")
    parser.add_argument("--dry-run", action="store_true", help="Shopify から取得するが書込はしない")
    args = parser.parse_args()

    if not SHOPIFY_TOKEN:
        raise SystemExit("ERROR: SHOPIFY_ADMIN_TOKEN が設定されていません（.env を確認）")
    if not SPREADSHEET_ID:
        raise SystemExit("ERROR: SPREADSHEET_ID_HOSPITAL が設定されていません")

    year, month = map(int, args.month.split("-"))
    year_month = f"{year}.{month}"

    print(f"=== 動物病院売上票 自動入力: {year_month} ===")
    if args.dry_run:
        print("(dry-run: 書込は行いません)\n")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID) if not args.dry_run else None

    for tag, config in HOSPITALS.items():
        print(f"\n[病院] {tag} (kickback {int(config['kickback_rate']*100)}%)")

        customers = get_customers_by_tag(tag)
        print(f"  対象顧客: {len(customers)} 名")
        if not customers:
            continue

        ws = None
        block_row = None
        if not args.dry_run:
            try:
                ws = sh.worksheet(config["sheet_name"])
            except gspread.WorksheetNotFound:
                print(f"  ⚠ シート '{config['sheet_name']}' が見つかりません（スキップ）")
                continue
            block_row = find_block_start_row(ws, year_month)
            if block_row is None:
                print(f"  ⚠ '{config['sheet_name']}' に {year_month} ブロックが見つかりません（スキップ）")
                continue

        for customer in customers:
            orders = get_orders_for_customer(customer["id"], year, month)
            pets = extract_pet_names(customer)
            if not orders:
                print(f"  -   {customer['displayName']}: {year_month} の注文なし")
                continue

            for order in orders:
                if args.dry_run:
                    subtotal = compute_subtotal_ex_tax(order)
                    kb = round(subtotal * config["kickback_rate"])
                    print(f"  [dry] {customer['displayName']} / {order['name']} / 税抜 ¥{subtotal:,} / KB ¥{kb:,} / pets={pets}")
                else:
                    data_col = find_empty_customer_col(ws, block_row)
                    write_order_to_sheet(
                        ws, block_row, data_col,
                        customer["displayName"], pets, order, year_month,
                        config["kickback_rate"],
                    )

    print("\n=== 完了 ===")


if __name__ == "__main__":
    main()
