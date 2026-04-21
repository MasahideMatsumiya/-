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

for pdf_path in pdf_files[:2]:
    print(f"\n{'='*50}")
    print(f"ファイル: {os.path.basename(pdf_path)}")
    print(f"{'='*50}")

    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]

        words = page.extract_words()

        # サイズラベルの中心座標を取得
        size_centers = {}
        for w in words:
            if w["text"] in ("CP", "60", "80", "100"):
                cx = (w["x0"] + w["x1"]) / 2
                cy = (w["top"] + w["bottom"]) / 2
                size_centers[w["text"]] = (cx, cy)

        print(f"\n[サイズラベル位置]:")
        for size, (cx, cy) in size_centers.items():
            print(f"  {size}: center x={cx:.1f} y={cy:.1f}")

        # 各サイズラベル付近の矩形
        print(f"\n[サイズラベル付近の矩形（距離60以内）]:")
        for size in ("CP", "60", "80", "100"):
            if size not in size_centers:
                print(f"\n  === {size} === (テキスト未検出)")
                continue
            cx, cy = size_centers[size]
            print(f"\n  === {size} (x={cx:.1f}, y={cy:.1f}) ===")
            nearby = []
            for r in page.rects:
                rcx = (r["x0"] + r["x1"]) / 2
                rcy = (r["top"] + r["bottom"]) / 2
                dist = ((rcx - cx) ** 2 + (rcy - cy) ** 2) ** 0.5
                if dist < 60:
                    nearby.append((dist, r))
            if not nearby:
                print("    (矩形なし)")
            for dist, r in sorted(nearby, key=lambda x: x[0]):
                lw   = r.get("linewidth", 0)
                fill = r.get("non_stroking_color", "なし")
                stroke = r.get("stroking_color", "なし")
                w_   = r["x1"] - r["x0"]
                h_   = r["bottom"] - r["top"]
                print(f"    dist={dist:.1f}  size={w_:.1f}x{h_:.1f}  lw={lw}  fill={fill}  stroke={stroke}")

        # linewidth > 0 の矩形
        nz = [r for r in page.rects if (r.get("linewidth") or 0) > 0]
        print(f"\n[linewidth > 0 の矩形]: {len(nz)} 件")
        for r in nz[:20]:
            print(f"  x0={r['x0']:.1f} x1={r['x1']:.1f} top={r['top']:.1f} bottom={r['bottom']:.1f} lw={r.get('linewidth',0)} fill={r.get('non_stroking_color','なし')}")

        # 全テキスト
        print("\n[全テキスト（最初の20行）]:")
        text = page.extract_text() or ""
        for i, line in enumerate(text.split("\n")[:20]):
            print(f"  {i+1}: {line}")
