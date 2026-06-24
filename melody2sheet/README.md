# melody2sheet 🎶

mp3などの**音源からメロディを自動採譜して譜面（楽譜）を作る**ツールです。

「ケツメイシの『仲間』のメロディだけ譜面にしたい」のような用途を想定しています。

## なぜ音源が必要？（コード譜では作れない理由）

コード譜（コード名＋歌詞）には **メロディの音の高さ（ドレミ）の情報が入っていません**。
コードは伴奏の和音を表すものなので、メロディ譜を作るには **曲の音源（mp3など）** が出発点になります。

## 処理の流れ

```
音源(mp3) → [任意] ボーカル抽出(demucs) → AI採譜(basic-pitch) → MIDI → 楽譜(MusicXML / PNG / PDF)
```

## セットアップ

```bash
pip install -r requirements.txt

# 環境によっては pkg_resources エラー回避のため:
pip install "setuptools<81"

# ボーカル抽出（--vocals）を使う場合のみ追加で:
pip install demucs

# PDF / PNG 出力（--pdf / --png）は MuseScore 不要（verovioで描画）
```

## 使い方

```bash
# いちばんシンプル: mp3からメロディ譜(MusicXML)を作る
python melody2sheet.py nakama.mp3

# ボーカルだけ抽出してから採譜（歌メロの精度が上がる）
python melody2sheet.py nakama.mp3 --vocals

# 譜面をPNG画像で出力（MuseScore不要・すぐ見られる）
python melody2sheet.py nakama.mp3 --png

# PDFまで出力（MuseScoreが必要）
python melody2sheet.py nakama.mp3 --pdf

# 曲名・キー・拍子を指定
python melody2sheet.py nakama.mp3 --title "仲間" --key Bb --time 4/4 -o out
```

出力された `*.musicxml` は無料の [MuseScore](https://musescore.org/) で開いて編集できます。

## オプション一覧

| オプション | 説明 |
|---|---|
| `-o, --out` | 出力先フォルダ（既定: `out`） |
| `--title` | 譜面のタイトル（既定: ファイル名） |
| `--key` | キー/調号（例: `Bb`, `C`, `Am`） |
| `--time` | 拍子（例: `4/4`, `3/4`） |
| `--vocals` | 採譜前にボーカルだけ抽出（精度UP / demucsが必要） |
| `--clean` | リズムを拍にスナップ(量子化)し短い音符を除去して読みやすくする |
| `--png` | PNG画像も出力（MuseScore不要 / verovio・cairosvgが必要） |
| `--pdf` | PDFも出力（MuseScore不要 / verovio・cairosvg・pypdfが必要） |
| `--polyphonic` | 単音化せず和音も残してそのまま譜面化 |

## 精度を上げるコツ

- **`--vocals`** でボーカルを抽出してから採譜すると、歌メロの精度が大きく上がります。
- **`--clean`** でリズムを量子化すると、音符の刻みが整理されて読みやすくなります。
- AI採譜は完璧ではありません。最後は MuseScore で耳で確認しながら手直しするのが現実的です。
- メロディが目立つ音源（歌メロがはっきりした曲）ほど良い結果になります。
  ラップ主体の曲は音程が曖昧なため、譜面が細かく刻まれやすい点に注意してください。

### 推奨コマンド（歌メロをきれいに出したいとき）

```bash
python melody2sheet.py song.mp3 --vocals --clean --png
```

## 🎼 ボーカル主旋律＋ピアノ伴奏＋コードの総譜（song2score.py）

`melody2sheet.py` は単旋律のメロディ譜ですが、`song2score.py` は
**上段＝ボーカル主旋律＋コードネーム / 下段＝ピアノ伴奏（大譜表）** の総譜を作ります。

```
音源 → ボーカル/伴奏に分離(demucs)
     → 主旋律を採譜 ─┐
     → 伴奏を採譜 ───┤→ music21で総譜化 → PDF(verovio+rsvg-convert)
     → コードを推定 ─┘
```

### 追加で必要なもの

```bash
pip install librosa pretty_midi   # コード推定・伴奏処理
# システムパッケージ:
apt-get install -y ffmpeg librsvg2-bin fonts-noto-cjk
#   ffmpeg        … demucsの音声入出力
#   librsvg2-bin  … 楽譜SVG→PDF変換(rsvg-convert)。記号・日本語を正しく描画
#   fonts-noto-cjk… PDFの日本語タイトル表示
```

### 使い方

```bash
# 総譜（主旋律＋コード＋ピアノ伴奏）
python song2score.py nakama.mp3 --title "仲間" --key Bb --pdf

# 出力パターンを選ぶ（--mode）
python song2score.py nakama.mp3 --mode melody --pdf   # 主旋律のみ
python song2score.py nakama.mp3 --mode lead   --pdf   # 主旋律＋コード
python song2score.py nakama.mp3 --mode piano  --pdf   # ピアノ伴奏のみ
python song2score.py nakama.mp3 --mode full   --pdf   # 総譜（既定）

# パーツを自由に組み合わせる（--parts）
python song2score.py nakama.mp3 --parts melody,piano --pdf
```

| オプション | 説明 |
|---|---|
| `--mode` | 出力プリセット: `melody` / `lead` / `piano` / `full`（既定: full） |
| `--parts` | パーツを自由指定（カンマ区切り）: `melody`,`chords`,`piano` |
| `--title` | 曲名（PDFのタイトル） |
| `--key` | 調号（既定: `Bb`）。コードもこのキー向けのフラット表記で表示 |
| `--pdf` | PDFを出力（複数ページ対応） |
| `--vocal-midi` / `--accomp-midi` / `--accomp-audio` | 採譜済み素材を使い回して高速化 |

> `--mode melody` のように不要なパートを外すと、その分の採譜・コード推定をスキップして高速化されます。

### 注意

- コードは音源からの**自動推定**（クロマ特徴 × 和音テンプレート）なので、概ね合っていても
  正確なオンコード（分数コード）や複雑なテンションまでは出ません。市販のコード譜と併用するのがおすすめです。
- ピアノ伴奏は「拍ごとのブロック和音」に整理した自動生成です。実際の細かな伴奏形までは再現しません。
- ラップ主体の曲は主旋律の音程が曖昧で、音符が細かくなりやすい点は単旋律版と同じです。

## 🌐 Webアプリ（ブラウザでmp3→譜面PDF）

コマンドライン操作なしで使える **Webアプリ** も同梱しています（`webapp/`）。
mp3をドラッグ＆ドロップ → 進捗表示 → 譜面PDFをダウンロード、という流れです。

```bash
pip install flask
python webapp/app.py   # → http://localhost:5000
```

詳しくは [`webapp/README.md`](webapp/README.md) を参照してください。

## ⚖️ 著作権について

採譜の対象が他者の楽曲（JASRAC管理曲など）の場合、**個人で楽しむ・練習する範囲**にとどめてください。
採譜データや譜面PDFを**配布・公開・販売することはできません**。
