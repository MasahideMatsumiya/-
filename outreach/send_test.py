#!/usr/bin/env python3
"""
テスト送信スクリプト（自分宛て専用）。

目的: 設定と文面が正しいかを、自分のアドレスに1通だけ送って確認する。
リストの施設には送りません。宛先は常に自分（GMAIL_USER か TEST_TO）です。

使い方:
  # 1) まず中身だけ確認（送信しない・認証不要）
  python3 outreach/send_test.py

  # 2) 実際に自分宛てへ1通テスト送信する
  export GMAIL_USER="あなたのアドレス@gmail.com"
  export GMAIL_APP_PASSWORD="16桁のアプリパスワード"   # 通常のログインPWではない
  export TEST_TO="ora.songokuu@docomo.ne.jp"          # 省略時は GMAIL_USER 宛て
  python3 outreach/send_test.py --send

アプリパスワードの取り方:
  Googleアカウント > セキュリティ > 2段階認証を有効化 > 「アプリ パスワード」で発行。
"""
import argparse
import json
import os
import re
import smtplib
import ssl
import sys
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

HERE = Path(__file__).parent
TPL = HERE / "template.txt"
CFG = HERE / "config.json"

FIELD_RE = re.compile(r"\{([^{}]+)\}")

# テスト用のダミー店舗（実在の施設には一切送らない）
SAMPLE_ROW = {
    "店舗名": "テスト宛（動作確認用）",
    "エリア": "東京",
    "業種": "ホテル/サロン",
}


def render(tpl: str, ctx: dict) -> str:
    return FIELD_RE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), tpl)


def build_message():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    tpl = TPL.read_text(encoding="utf-8")
    text = render(tpl, {**cfg, **SAMPLE_ROW})

    # 1行目の "SUBJECT: ..." を件名として取り出し、本文と分離
    lines = text.splitlines()
    subject = "（件名未設定）"
    if lines and lines[0].startswith("SUBJECT:"):
        subject = lines[0][len("SUBJECT:"):].strip()
        body = "\n".join(lines[1:]).lstrip("\n")
    else:
        body = text
    return cfg, subject, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="実際に送信する（既定はドライラン）")
    args = ap.parse_args()

    cfg, subject, body = build_message()

    if not args.send:
        print("=== ドライラン（送信しません） ===")
        print("To     : <自分のアドレス>  ※--send 時に GMAIL_USER / TEST_TO へ送信")
        print("Subject:", subject)
        print("-" * 40)
        print(body)
        print("-" * 40)
        print("\n問題なければ環境変数を設定して `--send` を付けて実行してください。")
        return

    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    to = os.environ.get("TEST_TO") or user
    if not user or not pw:
        sys.exit("GMAIL_USER と GMAIL_APP_PASSWORD を環境変数で設定してください。")

    # 安全装置: 宛先が自分自身か明示指定したテスト宛のみ許可（リスト送信防止）
    print(f"自分宛てテスト送信: {to}")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.get("sender_person", ""), user))
    msg["To"] = to

    ctx = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls(context=ctx)
        s.login(user, pw)
        s.sendmail(user, [to], msg.as_string())
    print("送信しました。受信トレイ（迷惑メールフォルダも）を確認してください。")


if __name__ == "__main__":
    main()
