#!/usr/bin/env python3
"""
リスト整形スクリプト
source_list.csv から「実際にメール送信できる行」だけを抽出し、
送信用のきれいなCSV(clean_list.csv)を書き出す。

- メールアドレス欄から最初の有効なアドレスを取り出す（複数併記・注釈混じりに対応）
- 形式が正しくない / 空の行は除外し、要確認リスト(needs_review.csv)に回す
- 個人ドメイン(gmail/icloud/yahoo等)は flag 列で警告
"""
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "source_list.csv"
OUT = HERE / "clean_list.csv"
REVIEW = HERE / "needs_review.csv"

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
PERSONAL_DOMAINS = ("gmail.com", "icloud.com", "yahoo.co.jp", "yahoo.com", "outlook.com", "hotmail.com")


def first_email(raw: str):
    """混在テキストから最初の妥当なメールアドレスを取り出す。無ければ None。"""
    if not raw:
        return None
    m = EMAIL_RE.search(raw)
    return m.group(0) if m else None


def main():
    if not SRC.exists():
        sys.exit(f"ソースが見つかりません: {SRC}")

    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    clean, review = [], []

    for r in rows:
        raw = (r.get("メールアドレス") or "").strip()
        email = first_email(raw)
        rec = {
            "営業No": r.get("営業No", ""),
            "店舗名": (r.get("店舗名") or "").strip(),
            "メールアドレス": email or "",
            "エリア": (r.get("エリア") or "").strip(),
            "業種": (r.get("業種") or "").strip(),
            "公式サイトURL": (r.get("公式サイトURL") or "").strip(),
            "flag": "",
            "元の記載": raw,
        }
        if not email:
            rec["flag"] = "メール無し(フォーム連絡のみ)" if not raw else "アドレス抽出不可"
            review.append(rec)
            continue
        # 複数併記や注釈付きは要確認に回しつつ、抽出結果は残す
        if raw != email:
            rec["flag"] = "要確認(元欄に複数/注釈)"
            review.append(rec)
            continue
        if any(email.lower().endswith("@" + d) for d in PERSONAL_DOMAINS):
            rec["flag"] = "個人ドメイン(送信前に要判断)"
        clean.append(rec)

    fields = ["営業No", "店舗名", "メールアドレス", "エリア", "業種", "公式サイトURL", "flag", "元の記載"]
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(clean)
    with REVIEW.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(review)

    print(f"総行数              : {len(rows)}")
    print(f"送信用に確定(clean) : {len(clean)}  -> {OUT.name}")
    print(f"要確認(review)      : {len(review)}  -> {REVIEW.name}")
    personal = sum(1 for c in clean if c["flag"])
    print(f"  うち個人ドメイン警告: {personal}")


if __name__ == "__main__":
    main()
