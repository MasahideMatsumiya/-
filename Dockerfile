FROM python:3.11-slim

WORKDIR /app

# 依存関係のインストール
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

# アプリのコピー
COPY src/ ./src/
COPY static/ ./static/

# 非rootユーザーで実行
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE ${PORT:-8000}

CMD uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}
