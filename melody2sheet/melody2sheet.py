#!/usr/bin/env python3
"""
melody2sheet — mp3などの音源からメロディを自動採譜して譜面（楽譜）を作るツール。

処理の流れ:
    音源(mp3) → [任意] ボーカル抽出(demucs) → AI採譜(basic-pitch) → MIDI → 楽譜(MusicXML / PDF)

コード譜（コード＋歌詞）にはメロディの音程情報が無いため、メロディ譜は音源から作ります。

使い方の例:
    # いちばんシンプル: mp3からメロディ譜(MusicXML)を作る
    python melody2sheet.py nakama.mp3

    # ボーカルだけ抽出してから採譜（歌メロの精度が上がる。demucsが必要）
    python melody2sheet.py nakama.mp3 --vocals

    # PDFまで出力（MuseScoreがインストールされていれば）
    python melody2sheet.py nakama.mp3 --pdf

    # 出力先と曲のキー/拍子を指定
    python melody2sheet.py nakama.mp3 -o out --title "仲間" --key Bb --time 4/4

必要なライブラリ:
    pip install basic-pitch music21
    # --vocals を使う場合のみ:
    pip install demucs
    # --pdf を使う場合は MuseScore 本体のインストールが必要:
    #   https://musescore.org/  (music21の設定が必要な場合あり)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def _fail(msg: str, hint: str | None = None) -> "NoReturn":  # type: ignore[name-defined]
    print(f"\n[エラー] {msg}", file=sys.stderr)
    if hint:
        print(f"  ヒント: {hint}", file=sys.stderr)
    sys.exit(1)


def separate_vocals(audio_path: Path, work_dir: Path) -> Path:
    """demucs で音源からボーカル(メロディ)トラックだけを抽出して返す。"""
    try:
        import demucs.separate  # noqa: F401  (存在確認のためだけにimport)
    except ImportError:
        _fail(
            "demucs が見つかりません（--vocals に必要）。",
            "pip install demucs でインストールしてください。",
        )

    print("[1/3] ボーカルを抽出中（demucs）… 初回はモデルのダウンロードで時間がかかります")
    out_root = work_dir / "demucs"
    # 2stems モデルで vocals / no_vocals に分離
    subprocess.run(
        [
            sys.executable, "-m", "demucs",
            "--two-stems", "vocals",
            "-o", str(out_root),
            str(audio_path),
        ],
        check=True,
    )
    # demucs は <out>/<model>/<曲名>/vocals.wav に出力する
    matches = list(out_root.rglob("vocals.wav"))
    if not matches:
        _fail("ボーカルトラックの抽出結果が見つかりませんでした。")
    return matches[0]


def transcribe_to_midi(audio_path: Path, out_dir: Path) -> Path:
    """basic-pitch で音源を採譜し、MIDIファイルのパスを返す。"""
    try:
        from basic_pitch.inference import predict_and_save
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError:
        _fail(
            "basic-pitch が見つかりません。",
            "pip install basic-pitch でインストールしてください。",
        )

    print("[2/3] AIでメロディを採譜中（basic-pitch）…")
    out_dir.mkdir(parents=True, exist_ok=True)
    predict_and_save(
        [str(audio_path)],
        str(out_dir),
        save_midi=True,
        sonify_midi=False,
        save_model_outputs=False,
        save_notes=False,
        model_or_model_path=ICASSP_2022_MODEL_PATH,
    )
    midis = sorted(out_dir.glob("*_basic_pitch.mid"))
    if not midis:
        _fail("MIDIの生成に失敗しました。")
    return midis[-1]


def midi_to_score(
    midi_path: Path,
    out_dir: Path,
    title: str,
    key: str | None,
    time_sig: str | None,
    monophonic: bool,
    clean: bool = False,
) -> list[Path]:
    """music21 で MIDI を楽譜(MusicXML / 任意でPDF)に変換する。"""
    try:
        import music21
    except ImportError:
        _fail(
            "music21 が見つかりません。",
            "pip install music21 でインストールしてください。",
        )

    print("[3/3] MIDIを楽譜に変換中（music21）…")
    score = music21.converter.parse(str(midi_path))

    # メロディは単音なので、和音が出たら一番高い音だけ残してメロディラインにする
    if monophonic:
        for chord in list(score.recurse().getElementsByClass("Chord")):
            top = max(chord.notes, key=lambda n: n.pitch.midi)
            new_note = music21.note.Note(top.pitch)
            new_note.duration = chord.duration
            chord.activeSite.replace(chord, new_note)

    # 整音（量子化）: リズムを拍にスナップし、短すぎる音符を除いて読みやすくする
    if clean:
        # 16分・3連のグリッドにスナップ
        score.quantize([4, 3], processOffsets=True, processDurations=True, inPlace=True)
        # 32分音符より短い、採譜ノイズらしき音を除去
        for n in list(score.recurse().notes):
            if n.duration.quarterLength < 0.25:
                if n.activeSite is not None:
                    n.activeSite.remove(n)

    # タイトル
    score.metadata = score.metadata or music21.metadata.Metadata()
    score.metadata.title = title
    score.metadata.composer = ""

    # キー（調号）の指定
    if key:
        try:
            ks = music21.key.Key(key.replace("b", "-"))  # 例: "Bb" -> "B-"
            score.parts[0].insert(0, ks) if score.parts else score.insert(0, ks)
        except Exception:
            print(f"  注意: キー '{key}' を解釈できなかったので調号は付けません。")

    # 拍子の指定
    if time_sig:
        try:
            ts = music21.meter.TimeSignature(time_sig)
            (score.parts[0] if score.parts else score).insert(0, ts)
        except Exception:
            print(f"  注意: 拍子 '{time_sig}' を解釈できなかったので付けません。")

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    xml_path = out_dir / f"{title}_melody.musicxml"
    score.write("musicxml", fp=str(xml_path))
    outputs.append(xml_path)

    return outputs


def render_pdf(xml_path: Path, out_dir: Path, title: str) -> Path | None:
    """MusicXML を verovio で複数ページのPDFにレンダリングする（MuseScore不要）。"""
    try:
        import io
        import verovio
        import cairosvg
        from pypdf import PdfWriter, PdfReader
    except ImportError:
        print(
            "  注意: PDF出力には verovio・cairosvg・pypdf が必要です。"
            " pip install verovio cairosvg pypdf を実行してください。"
        )
        return None

    tk = verovio.toolkit()
    # A4縦・余白付き
    tk.setOptions({
        "pageWidth": 2100, "pageHeight": 2970, "scale": 40, "adjustPageHeight": False,
        "pageMarginTop": 100, "pageMarginBottom": 100,
        "pageMarginLeft": 100, "pageMarginRight": 100,
    })
    if not tk.loadFile(str(xml_path)):
        print("  注意: PDFレンダリングで楽譜を読み込めませんでした。")
        return None

    writer = PdfWriter()
    for page in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(page)
        pdf_bytes = cairosvg.svg2pdf(bytestring=svg.encode())
        writer.add_page(PdfReader(io.BytesIO(pdf_bytes)).pages[0])

    pdf_path = out_dir / f"{title}_melody.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path


def render_png(xml_path: Path, out_dir: Path, title: str) -> Path | None:
    """MusicXML を verovio で SVG/PNG にレンダリングする（MuseScore不要）。"""
    try:
        import verovio
        import cairosvg
    except ImportError:
        print(
            "  注意: PNG出力には verovio と cairosvg が必要です。"
            " pip install verovio cairosvg を実行してください。"
        )
        return None

    tk = verovio.toolkit()
    tk.setOptions({"pageWidth": 2100, "scale": 45, "adjustPageHeight": True})
    if not tk.loadFile(str(xml_path)):
        print("  注意: PNGレンダリングで楽譜を読み込めませんでした。")
        return None
    svg = tk.renderToSVG(1)
    (out_dir / f"{title}_melody.svg").write_text(svg)
    png_path = out_dir / f"{title}_melody.png"
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(png_path), output_width=2100)
    return png_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="mp3などの音源からメロディを自動採譜して譜面を作ります。",
    )
    parser.add_argument("audio", help="入力音源（mp3 / wav など）")
    parser.add_argument("-o", "--out", default="out", help="出力先フォルダ（既定: out）")
    parser.add_argument("--title", default=None, help="曲名（譜面のタイトル。既定: ファイル名）")
    parser.add_argument("--key", default=None, help="キー/調号（例: Bb, C, Am）")
    parser.add_argument("--time", dest="time_sig", default=None, help="拍子（例: 4/4, 3/4）")
    parser.add_argument(
        "--vocals", action="store_true",
        help="採譜前にボーカルだけ抽出する（歌メロの精度UP。demucsが必要）",
    )
    parser.add_argument(
        "--pdf", action="store_true",
        help="PDFも出力する（MuseScore不要 / verovio・cairosvg・pypdfが必要）",
    )
    parser.add_argument(
        "--png", action="store_true",
        help="PNG画像も出力する（MuseScore不要 / verovio・cairosvgが必要）",
    )
    parser.add_argument(
        "--polyphonic", action="store_true",
        help="単音化せず採譜結果をそのまま譜面化する（和音も残す）",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="リズムを拍にスナップ(量子化)し短い音符を除去して読みやすくする",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio).expanduser().resolve()
    if not audio_path.exists():
        _fail(f"音源が見つかりません: {audio_path}")

    out_dir = Path(args.out).expanduser().resolve()
    title = args.title or audio_path.stem

    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    source_for_transcription = audio_path
    if args.vocals:
        source_for_transcription = separate_vocals(audio_path, work_dir)
    else:
        print("[1/3] ボーカル抽出はスキップ（--vocals で有効化できます）")

    midi_path = transcribe_to_midi(source_for_transcription, work_dir)

    outputs = midi_to_score(
        midi_path=midi_path,
        out_dir=out_dir,
        title=title,
        key=args.key,
        time_sig=args.time_sig,
        monophonic=not args.polyphonic,
        clean=args.clean,
    )

    xml_path = next((p for p in outputs if p.suffix == ".musicxml"), None)
    if args.pdf and xml_path:
        pdf_path = render_pdf(xml_path, out_dir, title)
        if pdf_path:
            outputs.append(pdf_path)
    if args.png and xml_path:
        png_path = render_png(xml_path, out_dir, title)
        if png_path:
            outputs.append(png_path)

    print("\n✅ 完成しました！")
    print(f"  MIDI : {midi_path}")
    for p in outputs:
        print(f"  譜面 : {p}")
    print(
        "\nヒント: 出力した .musicxml は無料の MuseScore で開いて手直しできます。"
        " AI採譜は完璧ではないので、最後は耳で確認して整えるのがおすすめです。"
    )


if __name__ == "__main__":
    main()
