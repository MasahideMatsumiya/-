#!/usr/bin/env python3
"""
clean_list.csv を Brevo 取り込み用CSV(brevo_contacts.csv)に変換する。

Brevoの「コンタクトのインポート」にそのまま読み込める列名にする:
  EMAIL (必須), STORE(店舗名), AREA(エリア), GENRE(業種), URL(公式サイト)
STORE などはBrevo側で「コンタクト属性」として作成しておくと差し込みに使える。
個人ドメイン(flag付き)は除外し、別ファイルに退避する。
"""
import csv
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "clean_list.csv"
OUT = HERE / "brevo_contacts.csv"
HELD = HERE / "brevo_hold_personal.csv"

COLS = ["EMAIL", "STORE", "AREA", "GENRE", "URL"]


def main():
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    send, hold = [], []
    for r in rows:
        rec = {
            "EMAIL": r.get("メールアドレス", "").strip(),
            "STORE": r.get("店舗名", "").strip(),
            "AREA": r.get("エリア", "").strip(),
            "GENRE": r.get("業種", "").strip(),
            "URL": r.get("公式サイトURL", "").strip(),
        }
        if not rec["EMAIL"]:
            continue
        # 個人ドメイン等のflag付きは送信前に個別判断 -> 退避
        (hold if r.get("flag") else send).append(rec)

    for path, data in ((OUT, send), (HELD, hold)):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(data)

    print(f"Brevo取り込み用: {len(send)}件 -> {OUT.name}")
    print(f"個別判断で保留 : {len(hold)}件 -> {HELD.name}")


if __name__ == "__main__":
    main()
