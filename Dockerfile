FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTH_DB_PATH=/data/auth.db \
    REPOSITORY_STORAGE_PATH=/data/repositories

WORKDIR /app

# Amosclaud needs Git for native repository operations.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/repositories

# Install the production runtime directly so Railway does not depend on a
# separate requirements.txt copy step or Docker layer ordering.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir \
        "fastapi>=0.110,<1" \
        "uvicorn[standard]>=0.29,<1" \
        "python-multipart>=0.0.9" \
        "python-jose[cryptography]>=3.3,<4" \
        "passlib>=1.7,<2" \
        "bcrypt>=4.1,<5" \
        "jinja2>=3.1.3" \
        "webauthn>=2.2,<3" \
        "pydantic>=2.7,<3" \
        "pydantic-settings>=2.2,<3" \
        "gitpython>=3.1,<4" \
        "requests>=2.31,<3" \
        "httpx>=0.27,<1" \
        "aiofiles>=23.2,<25" \
        "python-dotenv>=1.0,<2"

COPY . /app

# Fail with an explicit source-context error instead of a misleading missing
# dependency-file error.
RUN test -f /app/amoscloud_ai/main.py || (echo "Amosclaud source is missing from the Railway build context" && exit 1)

EXPOSE 8000

CMD ["sh", "-c", "uvicorn amoscloud_ai.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
