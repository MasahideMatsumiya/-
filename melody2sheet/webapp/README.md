# song2score Web アプリ 🎼

ブラウザで **mp3をアップロード → 進捗表示 → 譜面PDFをプレビュー＆ダウンロード** できる
Webアプリです。`song2score.py`（ボーカル主旋律＋コード＋ピアノ伴奏）をそのまま使います。

## セットアップ

```bash
# プロジェクトの依存をすべて入れる
pip install -r ../requirements.txt
pip install demucs            # ボーカル分離に必要

# システムパッケージ（採譜・PDF描画に必要）
apt-get install -y ffmpeg librsvg2-bin fonts-noto-cjk
```

## 起動

```bash
python app.py
# → ブラウザで http://localhost:5000 を開く
```

## 使い方

1. mp3 をドラッグ＆ドロップ（またはクリックして選択）
2. 曲名・キーを入力
3. 「譜面を作る」を押す
4. 進捗バーが進み、完成したら **PDF / MusicXML** をダウンロード、譜面プレビューも表示

## 仕組み

```
ブラウザ ──mp3──▶ Flask(/upload) ──▶ バックグラウンドスレッド
                                      ├ demucs        分離
                                      ├ basic-pitch   主旋律・伴奏を採譜
                                      ├ librosa       コード推定
                                      ├ music21       総譜化(MusicXML)
                                      └ verovio+rsvg  PDF/プレビュー生成
ブラウザ ◀─進捗ポーリング(/status)─┘
ブラウザ ◀─PDF/XML/PNG(/file)─────┘
```

- ジョブは `job_id` ごとに `results/<job_id>/` に保存されます。
- 処理は数分かかります（曲の長さ・サーバー性能による）。タブは開いたままにしてください。

## 注意 / 今後の改善案

- 現在はローカル単一ユーザー向けの簡易構成（ジョブ状態はメモリ保持）。
  公開運用するなら、ジョブキュー(Celery/RQ)・永続化・アップロードサイズ制限・認証の追加を推奨。
- 採譜・コードは自動推定なので、最終的な精度は元のコード譜と併用して手直しするのが現実的です。
