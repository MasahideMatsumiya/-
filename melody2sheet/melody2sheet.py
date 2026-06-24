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
    make_pdf: bool,
    monophonic: bool,
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

    if make_pdf:
        try:
            pdf_path = out_dir / f"{title}_melody.pdf"
            score.write("musicxml.pdf", fp=str(pdf_path))
            outputs.append(pdf_path)
        except Exception as e:
            print(
                "  注意: PDF出力に失敗しました（MuseScore未インストールの可能性）。"
                f" MusicXMLは出力済みです。詳細: {e}"
            )

    return outputs


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
    parser.add_argument("--pdf", action="store_true", help="PDFも出力する（MuseScoreが必要）")
    parser.add_argument(
        "--polyphonic", action="store_true",
        help="単音化せず採譜結果をそのまま譜面化する（和音も残す）",
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
        make_pdf=args.pdf,
        monophonic=not args.polyphonic,
    )

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
