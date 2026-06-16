#!/usr/bin/env python3
import csv, os
BASE="/home/user/-"
src=os.path.join(BASE,"buddybuddy_petshop_master_nationwide.csv")
rows=list(csv.DictReader(open(src,encoding="utf-8")))

sales=[]
for r in rows:
    m = r["メール公開"]=="○"
    f = r["問い合わせフォーム"]=="○"
    if not (m or f):
        continue
    means = "メール+フォーム" if (m and f) else ("メール" if m else "フォーム")
    sales.append({**r, "連絡手段": means})

# priority: メール持ち(両方→メール)を先頭、その後フォームのみ。各群は元の通し番号順
order={"メール+フォーム":0,"メール":1,"フォーム":2}
sales.sort(key=lambda r:(order[r["連絡手段"]], int(r["通し番号"])))

cols=["営業No","連絡手段","メールアドレス","エリア","店舗名","業種","公式サイトURL","電話","元リスト","元No","備考"]
out=os.path.join(BASE,"buddybuddy_petshop_contactable_sales.csv")
with open(out,"w",encoding="utf-8",newline="") as fp:
    w=csv.DictWriter(fp,fieldnames=cols); w.writeheader()
    for i,r in enumerate(sales,1):
        w.writerow({
            "営業No": i,
            "連絡手段": r["連絡手段"],
            "メールアドレス": r["メールアドレス"],
            "エリア": r["エリア"],
            "店舗名": r["店舗名"],
            "業種": r["業種"],
            "公式サイトURL": r["公式サイトURL"],
            "電話": r["電話"],
            "元リスト": r["元リスト"],
            "元No": r["通し番号"],
            "備考": r["備考"],
        })
from collections import Counter
c=Counter(r["連絡手段"] for r in sales)
print("営業リスト総数:", len(sales))
for k in ["メール+フォーム","メール","フォーム"]:
    print(f"  {k}: {c[k]}")
print("  メール持ち合計:", c["メール+フォーム"]+c["メール"])
