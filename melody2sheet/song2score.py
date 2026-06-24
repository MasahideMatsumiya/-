#!/usr/bin/env python3
"""
song2score — 音源(mp3など)から「ボーカル主旋律＋ピアノ伴奏＋コードネーム」の楽譜を作る。

melody2sheet.py がメロディ単旋律の譜面を作るのに対し、こちらは
リードシート(主旋律+コード)とピアノ伴奏(大譜表)をまとめた総譜を作ります。

処理の流れ:
    音源 → ボーカル/伴奏に分離(demucs)
         → 主旋律を採譜(basic-pitch) ─┐
         → 伴奏を採譜(basic-pitch) ───┤→ music21で総譜化 → PDF(verovio+rsvg)
         → コードを推定(librosa) ─────┘

使い方:
    python song2score.py nakama.mp3 --title "仲間" --key Bb --pdf

必要なもの:
    pip install basic-pitch music21 demucs librosa pretty_midi numpy verovio
    システム: ffmpeg, rsvg-convert(librsvg2-bin), 日本語表示には fonts-noto-cjk
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BPM = 120                 # 内部テンポ（basic-pitchのMIDI既定に合わせる）
SEC2Q = BPM / 60.0        # 秒 → 四分音符offset (120BPMなら ×2)
STEP_S = 0.5              # ピアノ伴奏のサンプリング間隔（1拍=0.5秒）
# フラット表記（B♭メジャー系の曲で読みやすい）
NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']


def _fail(msg: str, hint: str | None = None):
    print(f"\n[エラー] {msg}", file=sys.stderr)
    if hint:
        print(f"  ヒント: {hint}", file=sys.stderr)
    sys.exit(1)


def separate_stems(audio_path: Path, work_dir: Path) -> tuple[Path, Path]:
    """demucsで音源を vocals(主旋律) と no_vocals(伴奏) に分離する。"""
    print("[1/5] ボーカルと伴奏を分離中（demucs）…")
    out_root = work_dir / "demucs"
    subprocess.run(
        [sys.executable, "-m", "demucs", "--two-stems", "vocals",
         "-o", str(out_root), str(audio_path)],
        check=True,
    )
    vocals = next(iter(out_root.rglob("vocals.wav")), None)
    accomp = next(iter(out_root.rglob("no_vocals.wav")), None)
    if not vocals or not accomp:
        _fail("分離結果(vocals.wav / no_vocals.wav)が見つかりませんでした。")
    return vocals, accomp


def transcribe(audio_path: Path, out_dir: Path, label: str) -> Path:
    """basic-pitchで採譜してMIDIパスを返す。"""
    from basic_pitch.inference import predict_and_save
    from basic_pitch import ICASSP_2022_MODEL_PATH
    out_dir.mkdir(parents=True, exist_ok=True)
    predict_and_save([str(audio_path)], str(out_dir), save_midi=True,
                     sonify_midi=False, save_model_outputs=False, save_notes=False,
                     model_or_model_path=ICASSP_2022_MODEL_PATH)
    midis = sorted(out_dir.glob("*_basic_pitch.mid"))
    if not midis:
        _fail(f"{label}のMIDI生成に失敗しました。")
    return midis[-1]


def estimate_chords(audio_path: Path) -> list[tuple[float, str]]:
    """伴奏音源からコード進行を推定し [(四分offset, 'Bb'等), ...] を返す。"""
    import librosa
    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    _, beats = librosa.beat.beat_track(y=y, sr=sr)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    csync = librosa.util.sync(chroma, beats, aggregate=np.median)
    btimes = librosa.frames_to_time(beats, sr=sr)
    maj = np.array([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0.0])
    mint = np.array([1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0.0])
    T, labels = [], []
    for i in range(12):
        T.append(np.roll(maj, i)); labels.append(NAMES[i])
        T.append(np.roll(mint, i)); labels.append(NAMES[i] + 'm')
    Tn = np.array(T) / np.linalg.norm(T, axis=1, keepdims=True)
    out = []
    for j in range(csync.shape[1]):
        v = csync[:, j]
        if v.sum() < 1e-3:
            continue
        s = Tn @ (v / (np.linalg.norm(v) + 1e-9))
        t = btimes[j] if j < len(btimes) else btimes[-1]
        out.append((t * SEC2Q, labels[int(np.argmax(s))]))
    merged = []
    for q, c in out:
        if not merged or merged[-1][1] != c:
            merged.append((q, c))
    return merged


def build_melody(vocal_midi: Path, key_name: str, title: str):
    """主旋律パート(単音・量子化)を作る。"""
    import music21
    from music21 import stream, note, clef, tempo, meter, key as m21key
    parsed = music21.converter.parse(str(vocal_midi))
    for ch in list(parsed.recurse().getElementsByClass('Chord')):
        n = note.Note(max(ch.notes, key=lambda x: x.pitch.midi).pitch)
        n.duration = ch.duration
        ch.activeSite.replace(ch, n)
    parsed.quantize([4], processOffsets=True, processDurations=True, inPlace=True)
    for n in list(parsed.recurse().notes):
        if n.duration.quarterLength < 0.25 and n.activeSite is not None:
            n.activeSite.remove(n)
    mel_notes = parsed.flatten().notes.stream()
    part = stream.Part()
    part.partName = 'Vocal'
    part.insert(0, clef.TrebleClef())
    part.insert(0, tempo.MetronomeMark(number=BPM))
    part.insert(0, meter.TimeSignature('4/4'))
    if key_name:
        try:
            part.insert(0, m21key.Key(key_name.replace('b', '-')))
        except Exception:
            pass
    for n in mel_notes:
        part.insert(n.offset, n)
    maxoff = max([n.offset + n.duration.quarterLength for n in mel_notes], default=0)
    return part, maxoff, len(mel_notes)


def add_chords(melody_part, chords, maxoff):
    """主旋律段の上にコード名（通常テキスト）を載せる。"""
    from music21 import expressions
    for q, lab in chords:
        if q > maxoff + 4:
            break
        try:
            te = expressions.TextExpression(lab)
            te.placement = 'above'
            te.style.fontWeight = 'bold'
            melody_part.insert(round(q * 4) / 4.0, te)
        except Exception:
            pass


def build_piano(accomp_midi: Path, total_q: int):
    """伴奏MIDIから拍ごとのブロック和音でピアノ大譜表(RH/LH)を作る。"""
    import pretty_midi
    import music21
    from music21 import stream, chord, clef, meter, duration, pitch
    pm = pretty_midi.PrettyMIDI(str(accomp_midi))
    mnotes = [(n.start, n.end, n.pitch) for inst in pm.instruments for n in inst.notes]
    grid = []
    for kq in range(total_q):
        t0, t1 = kq * STEP_S, (kq + 1) * STEP_S
        grid.append(tuple(sorted({p for (s, e, p) in mnotes if s < t1 and e > t0})))
    segs = []  # [start_q, len_q, pitches]
    for kq, ps in enumerate(grid):
        if segs and segs[-1][2] == ps:
            segs[-1][1] += 1
        else:
            segs.append([kq, 1, ps])
    rh = stream.PartStaff(); rh.insert(0, clef.TrebleClef())
    lh = stream.PartStaff(); lh.insert(0, clef.BassClef())
    for start_q, len_q, ps in segs:
        if not ps:
            continue
        hi = [pitch.Pitch(m) for m in ps if m >= 60][:4]
        lo = [pitch.Pitch(m) for m in ps if m < 60][-2:]
        if hi:
            c = chord.Chord(hi); c.duration = duration.Duration(float(len_q)); rh.insert(start_q, c)
        if lo:
            c = chord.Chord(lo); c.duration = duration.Duration(float(len_q)); lh.insert(start_q, c)
    rh.insert(0, meter.TimeSignature('4/4'))
    lh.insert(0, meter.TimeSignature('4/4'))
    return rh, lh


def piano_length_q(accomp_midi: Path) -> int:
    """伴奏MIDIの長さ（四分音符数）を返す。ピアノ単独出力で小節数を決めるのに使う。"""
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(accomp_midi))
    end = max((n.end for inst in pm.instruments for n in inst.notes), default=0.0)
    return int(np.ceil(end * SEC2Q)) or 60


def assemble(melody_part, piano, title: str, out_xml: Path):
    """選択されたパートだけで総譜を組む。

    melody_part: 主旋律パート（無ければ None）
    piano:       (rh, lh) のタプル（無ければ None）
    """
    from music21 import stream, layout, metadata
    parts = []
    if melody_part is not None:
        parts.append(melody_part)
    if piano is not None:
        parts.extend(piano)  # rh, lh
    for part in parts:
        part.makeNotation(inPlace=True)
    score = stream.Score()
    score.insert(0, metadata.Metadata())
    score.metadata.title = title
    for part in parts:
        score.insert(0, part)
    if piano is not None:
        rh, lh = piano
        score.insert(0, layout.StaffGroup(
            [rh, lh], name='Piano', abbreviation='Pf.', symbol='brace'))
    score.write('musicxml', fp=str(out_xml))
    return out_xml


def render_pdf(xml_path: Path, pdf_path: Path) -> Path | None:
    """verovioで多ページSVG→rsvg-convertで1つのPDFに結合（日本語・記号も正しく描画）。"""
    import verovio
    tk = verovio.toolkit()
    tk.setOptions({
        "pageWidth": 2100, "pageHeight": 2970, "scale": 42, "adjustPageHeight": False,
        "pageMarginTop": 100, "pageMarginBottom": 100,
        "pageMarginLeft": 100, "pageMarginRight": 100,
    })
    if not tk.loadFile(str(xml_path)):
        _fail("PDFレンダリングで楽譜を読み込めませんでした。")
    with tempfile.TemporaryDirectory() as td:
        svgs = []
        for p in range(1, tk.getPageCount() + 1):
            sp = Path(td) / f"page{p:03d}.svg"
            sp.write_text(tk.renderToSVG(p))
            svgs.append(str(sp))
        if not shutil_which("rsvg-convert"):
            _fail("rsvg-convert が見つかりません。",
                  "apt-get install -y librsvg2-bin を実行してください。")
        subprocess.run(["rsvg-convert", "-f", "pdf", "-b", "white",
                        "-o", str(pdf_path), *svgs], check=True)
    return pdf_path


def shutil_which(cmd: str):
    import shutil
    return shutil.which(cmd)


VALID_PARTS = ("melody", "chords", "piano")

# よく使う組み合わせのプリセット
PRESETS = {
    "melody": ["melody"],                    # 主旋律のみ
    "lead":   ["melody", "chords"],          # 主旋律＋コード（リードシート）
    "piano":  ["piano"],                     # ピアノ伴奏のみ
    "full":   ["melody", "chords", "piano"],  # 総譜（既定）
}


def generate(audio: Path, out_dir: Path, title: str, key: str,
             parts: list[str], want_pdf: bool = True,
             progress=None,
             vocal_midi: Path | None = None,
             accomp_midi: Path | None = None,
             accomp_audio: Path | None = None) -> dict:
    """選択したパート(melody/chords/piano)だけの楽譜を作る共通処理。

    progress: 進捗文字列を受け取るコールバック（Webアプリ用）。
    戻り値: {'musicxml':Path, 'pdf':Path|None, 'n_mel':int, 'n_chords':int}
    """
    def say(msg):
        if progress:
            progress(msg)
        else:
            print(msg)

    parts = [p for p in parts if p in VALID_PARTS] or ["melody"]
    need_melody = "melody" in parts
    need_chords = "chords" in parts
    need_piano = "piano" in parts

    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "_work"
    work.mkdir(parents=True, exist_ok=True)

    have_materials = bool(vocal_midi and accomp_midi and accomp_audio)
    need_sep = (need_melody or need_piano or need_chords) and not have_materials
    if need_sep:
        say("ボーカルと伴奏を分離中…(demucs)")
        vocals, accomp_audio = separate_stems(audio, work)
        if need_melody:
            say("主旋律を採譜中…(basic-pitch)")
            vocal_midi = transcribe(vocals, work / "vocal", "主旋律")
        if need_piano:
            say("伴奏を採譜中…(basic-pitch)")
            accomp_midi = transcribe(accomp_audio, work / "accomp", "伴奏")

    chords = []
    if need_chords:
        say("コードを推定中…(librosa)")
        chords = estimate_chords(accomp_audio)

    say("譜面を組み立て中…(music21)")
    melody_part, piano = None, None
    n_mel, maxoff = 0, 0
    if need_melody:
        melody_part, maxoff, n_mel = build_melody(vocal_midi, key, title)
    if need_piano:
        total_q = int(np.ceil(maxoff)) if maxoff else piano_length_q(accomp_midi)
        rh, lh = build_piano(accomp_midi, total_q)
        piano = (rh, lh)
    # コードは一番上の段（無ければピアノ右手）の上に載せる
    if need_chords:
        top = melody_part if melody_part is not None else (piano[0] if piano else None)
        if top is not None:
            length = maxoff or piano_length_q(accomp_midi)
            add_chords(top, chords, length)

    xml_path = out_dir / f"{title}_score.musicxml"
    assemble(melody_part, piano, title, xml_path)

    pdf_path = None
    if want_pdf:
        say("PDFを生成中…(verovio+rsvg)")
        pdf_path = render_pdf(xml_path, out_dir / f"{title}_score.pdf")

    return {"musicxml": xml_path, "pdf": pdf_path,
            "n_mel": n_mel, "n_chords": len(chords)}


def main():
    ap = argparse.ArgumentParser(
        description="音源から楽譜を作ります（出力パーツを選択可能）。")
    ap.add_argument("audio", help="入力音源(mp3/wav)")
    ap.add_argument("-o", "--out", default="out", help="出力先フォルダ")
    ap.add_argument("--title", default=None, help="曲名(既定: ファイル名)")
    ap.add_argument("--key", default="Bb", help="調号(既定: Bb)")
    ap.add_argument("--pdf", action="store_true", help="PDFを出力する")
    ap.add_argument("--mode", choices=list(PRESETS), default=None,
                    help="出力プリセット: melody/lead/piano/full(既定)")
    ap.add_argument("--parts", default=None,
                    help="出力パーツをカンマ区切りで指定: melody,chords,piano")
    # 既に分離/採譜済みの素材を使い回す（再計算を省いて高速化）
    ap.add_argument("--vocal-midi", default=None, help="採譜済みの主旋律MIDIを使う")
    ap.add_argument("--accomp-midi", default=None, help="採譜済みの伴奏MIDIを使う")
    ap.add_argument("--accomp-audio", default=None, help="コード推定に使う伴奏音源")
    args = ap.parse_args()

    audio = Path(args.audio).expanduser().resolve()
    if not audio.exists():
        _fail(f"音源が見つかりません: {audio}")
    out_dir = Path(args.out).expanduser().resolve()
    title = args.title or audio.stem

    if args.parts:
        parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    else:
        parts = PRESETS[args.mode or "full"]

    res = generate(
        audio, out_dir, title, args.key, parts, want_pdf=args.pdf,
        vocal_midi=Path(args.vocal_midi) if args.vocal_midi else None,
        accomp_midi=Path(args.accomp_midi) if args.accomp_midi else None,
        accomp_audio=Path(args.accomp_audio) if args.accomp_audio else None,
    )

    print("\n✅ 完成しました！")
    print(f"  出力パーツ: {', '.join(parts)}")
    print(f"  メロディ音数: {res['n_mel']}  コード数: {res['n_chords']}")
    print(f"  出力 : {res['musicxml']}")
    if res["pdf"]:
        print(f"  出力 : {res['pdf']}")


if __name__ == "__main__":
    main()
