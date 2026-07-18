FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTH_DB_PATH=/data/auth.db \
    REPOSITORY_STORAGE_PATH=/data/repositories

WORKDIR /app

# The autonomous agent runs git status checks. The slim Python image does not
# include git, which caused /api/v1/agent/run to return HTTP 500 on Railway.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/repositories

COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn amoscloud_ai.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
