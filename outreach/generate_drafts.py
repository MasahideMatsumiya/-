#!/usr/bin/env python3
"""
下書きプレビュー生成スクリプト（送信はしません）。

clean_list.csv の各行に template.txt + config.json を差し込んで、
- drafts/ 配下に1件ずつのテキスト下書き
- drafts_preview.md に全件まとめプレビュー
を書き出す。中身を目視チェックするための「テスト」用途。

実際の送信は行わない。最終的にはBrevo等の配信サービスへ
clean_list.csv を取り込むか、内容を確認のうえ手動送信すること。
"""
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
LIST = HERE / "clean_list.csv"
TPL = HERE / "template.txt"
CFG = HERE / "config.json"
OUTDIR = HERE / "drafts"
PREVIEW = HERE / "drafts_preview.md"

FIELD_RE = re.compile(r"\{([^{}]+)\}")


def render(tpl: str, ctx: dict) -> str:
    """{key} を ctx[key] に置換。未知のキーはそのまま残して気付けるようにする。"""
    return FIELD_RE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), tpl)


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    tpl = TPL.read_text(encoding="utf-8")
    rows = list(csv.DictReader(LIST.open(encoding="utf-8")))

    OUTDIR.mkdir(exist_ok=True)
    for old in OUTDIR.glob("*.txt"):
        old.unlink()

    preview_parts = [f"# 下書きプレビュー（全{len(rows)}件・送信前チェック用）\n"]
    for r in rows:
        ctx = {**cfg, **r}
        body = render(tpl, ctx)
        no = r.get("営業No", "x")
        name = re.sub(r"[^\w一-龥ぁ-んァ-ヶー]+", "_", r.get("店舗名", "noname"))[:20]
        (OUTDIR / f"{no}_{name}.txt").write_text(body, encoding="utf-8")

        warn = f"  ⚠️ {r['flag']}" if r.get("flag") else ""
        preview_parts.append(
            f"\n---\n\n## No.{no} {r.get('店舗名','')} <{r.get('メールアドレス','')}>{warn}\n\n```\n{body}\n```\n"
        )

    PREVIEW.write_text("\n".join(preview_parts), encoding="utf-8")
    print(f"下書き生成: {len(rows)}件 -> {OUTDIR}/ , まとめ -> {PREVIEW.name}")
    unresolved = sorted({m for r in rows for m in FIELD_RE.findall(render(tpl, {**cfg, **r}))})
    if unresolved:
        print("未差し込みのプレースホルダ（config.txtを埋めてください）:", unresolved)


if __name__ == "__main__":
    main()
