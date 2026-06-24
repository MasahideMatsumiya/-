#!/usr/bin/env python3
"""
song2score / melody2sheet の Webアプリ。

ブラウザで mp3 をアップロード → バックグラウンドで採譜・譜面化 →
進捗を表示し、完成したら譜面PDFをプレビュー＆ダウンロードできる。

起動:
    pip install flask
    python webapp/app.py
    → http://localhost:5000 を開く
"""
from __future__ import annotations

import importlib.util
import threading
import traceback
import uuid
from pathlib import Path

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, abort)
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
TOOL_DIR = BASE.parent          # melody2sheet/
UPLOADS = BASE / "uploads"
RESULTS = BASE / "results"
UPLOADS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, TOOL_DIR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ツール本体を関数として読み込む
s2s = _load("song2score", "song2score.py")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB

# job_id -> {state, step, error, files}
JOBS: dict[str, dict] = {}


def run_job(job_id: str, audio_path: Path, title: str, key: str, parts: list[str]):
    job = JOBS[job_id]
    out_dir = RESULTS / job_id
    try:
        job.update(state="running", step="準備中…")

        def progress(msg):
            job.update(step=msg)

        res = s2s.generate(audio_path, out_dir, title, key, parts,
                           want_pdf=True, progress=progress)

        # プレビュー用に1ページ目のPNGも作る
        png_path = out_dir / "preview.png"
        _render_preview(res["musicxml"], png_path)

        job.update(
            state="done", step="完成しました！",
            n_mel=res["n_mel"], n_chords=res["n_chords"],
            files={
                "pdf": res["pdf"].name if res["pdf"] else None,
                "musicxml": res["musicxml"].name,
                "preview": png_path.name if png_path.exists() else None,
            },
        )
    except Exception as e:
        job.update(state="error", step="エラーが発生しました",
                   error=f"{e}\n{traceback.format_exc()}")


def _render_preview(xml_path: Path, png_path: Path):
    """1ページ目をPNGプレビュー化（失敗しても致命的でない）。"""
    try:
        import subprocess
        import verovio
        tk = verovio.toolkit()
        tk.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": 42,
                       "adjustPageHeight": True, "pageMarginLeft": 100,
                       "pageMarginRight": 100, "pageMarginTop": 100})
        if not tk.loadFile(str(xml_path)):
            return
        svg_path = png_path.with_suffix(".svg")
        svg_path.write_text(tk.renderToSVG(1))
        subprocess.run(["rsvg-convert", "-w", "1400", "-b", "white",
                        str(svg_path), "-o", str(png_path)], check=True)
    except Exception:
        pass


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify(error="音源ファイルを選んでください。"), 400
    title = (request.form.get("title") or Path(f.filename).stem).strip()
    key = (request.form.get("key") or "Bb").strip()
    mode = (request.form.get("mode") or "full").strip()
    parts = s2s.PRESETS.get(mode, s2s.PRESETS["full"])

    job_id = uuid.uuid4().hex[:12]
    safe = secure_filename(f.filename) or "audio.mp3"
    audio_path = UPLOADS / f"{job_id}_{safe}"
    f.save(audio_path)

    JOBS[job_id] = {"state": "queued", "step": "順番待ち…", "title": title}
    threading.Thread(target=run_job, args=(job_id, audio_path, title, key, parts),
                     daemon=True).start()
    return jsonify(job_id=job_id)


@app.route("/status/<job_id>")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="不明なジョブです。"), 404
    return jsonify({k: v for k, v in job.items() if k != "error_full"})


@app.route("/file/<job_id>/<path:name>")
def result_file(job_id: str, name: str):
    if job_id not in JOBS:
        abort(404)
    return send_from_directory(RESULTS / job_id, name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
