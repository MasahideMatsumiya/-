#!/usr/bin/env python3
import csv, glob, os

SRC = [
    ("初回", "buddybuddy_petshop_list_verified.csv"),
    ("追加1", "buddybuddy_petshop_list_additional_verified.csv"),
    ("追加2", "buddybuddy_petshop_list_additional2_verified.csv"),
]
BASE = "/home/user/-"

def mail_flag(v):
    v = v.strip()
    if "確認不可" in v:
        return "不明", ""
    if v.startswith("公開あり"):
        addr = v.split(":", 1)[1].strip() if ":" in v else ""
        return "○", addr
    return "×", ""

def form_flag(v):
    v = v.strip()
    if "確認不可" in v:
        return "不明"
    if v.startswith("あり"):
        return "○"
    return "×"

rows = []
for label, fn in SRC:
    with open(os.path.join(BASE, fn), encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            mf, addr = mail_flag(row["メール"])
            rows.append({
                "通し番号": 0,
                "元リスト": label,
                "エリア": row["エリア"],
                "店舗名": row["店舗名"],
                "業種": row["業種"],
                "公式サイトURL": row["公式サイトURL"],
                "電話": row.get("電話(検索で判明分)", ""),
                "メール公開": mf,
                "メールアドレス": addr,
                "問い合わせフォーム": form_flag(row["問い合わせフォーム"]),
                "備考": row["備考"],
            })

for i, row in enumerate(rows, 1):
    row["通し番号"] = i

cols = ["通し番号","元リスト","エリア","店舗名","業種","公式サイトURL","電話",
        "メール公開","メールアドレス","問い合わせフォーム","備考"]
out = os.path.join(BASE, "buddybuddy_petshop_master_nationwide.csv")
with open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)

# summary
def count(key, val):
    return sum(1 for r in rows if r[key] == val)
print(f"総数: {len(rows)}")
print(f"メール公開 ○: {count('メール公開','○')} / × : {count('メール公開','×')} / 不明: {count('メール公開','不明')}")
print(f"フォーム  ○: {count('問い合わせフォーム','○')} / × : {count('問い合わせフォーム','×')} / 不明: {count('問い合わせフォーム','不明')}")
contactable = sum(1 for r in rows if r['メール公開']=='○' or r['問い合わせフォーム']=='○')
print(f"メールまたはフォームで連絡可能: {contactable}")
from collections import Counter
c = Counter(r['エリア'] for r in rows)
print("エリア数:", len(c))
