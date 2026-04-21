#!/usr/bin/env python3
"""PDFの内部構造を確認するデバッグスクリプト"""
import sys
import glob
import os
import pdfplumber

PDF_FOLDER = "./pdfs"

pdf_files = sorted(glob.glob(os.path.join(PDF_FOLDER, "*.pdf")))
if not pdf_files:
    print("pdfs/ フォルダにPDFがありません")
    sys.exit(1)

for pdf_path in pdf_files[:2]:  # 最初の2件だけ確認
    print(f"\n{'='*50}")
    print(f"ファイル: {os.path.basename(pdf_path)}")
    print(f"{'='*50}")

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]

        # テキストワード一覧
        words = page.extract_words()
        print("\n[テキスト] CP/60/80/100 に関係する単語:")
        for w in words:
            if any(x in w["text"] for x in ("CP", "60", "80", "100", "配送", "サイズ")):
                print(f"  '{w['text']}' x0={w['x0']:.1f} top={w['top']:.1f}")

        print(f"\n[矩形] 全 {len(page.rects)} 件（上位10件）:")
        for r in sorted(page.rects, key=lambda x: x.get("linewidth", 0), reverse=True)[:10]:
            lw = r.get("linewidth", 0)
            fill = r.get("non_stroking_color", "なし")
            print(f"  x0={r['x0']:.1f} x1={r['x1']:.1f} top={r['top']:.1f} bottom={r['bottom']:.1f} lw={lw} fill={fill}")

        # 全テキスト
        print("\n[全テキスト抜粋（最初の20行）]:")
        text = page.extract_text() or ""
        for i, line in enumerate(text.split("\n")[:20]):
            print(f"  {i+1}: {line}")
