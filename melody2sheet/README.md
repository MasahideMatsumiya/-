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

# PDF出力（--pdf）を使う場合は MuseScore 本体が必要:
#   https://musescore.org/
#   ※ PNG画像（--png）なら MuseScore 不要（verovioで描画）
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
| `--pdf` | PDFも出力（MuseScoreが必要） |
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

## ⚖️ 著作権について

採譜の対象が他者の楽曲（JASRAC管理曲など）の場合、**個人で楽しむ・練習する範囲**にとどめてください。
採譜データや譜面PDFを**配布・公開・販売することはできません**。
