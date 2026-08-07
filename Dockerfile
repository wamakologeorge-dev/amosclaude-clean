FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTH_DB_PATH=/data/auth.db \
    REPOSITORY_STORAGE_PATH=/data/repositories \
    AMOSCLAUD_MANAGED_TERMINAL_ENABLED=true

WORKDIR /app

# The public Railway service now includes a non-root managed terminal fallback.
# These packages provide the same practical run/debug/diagnostic experience when
# a separate Docker workspace host is not connected.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        fd-find \
        gdb \
        git \
        iproute2 \
        jq \
        less \
        lsof \
        nano \
        net-tools \
        nodejs \
        npm \
        procps \
        ripgrep \
        strace \
        tmux \
        unzip \
        vim-tiny \
        zip \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data/repositories /tmp/amosclaud-managed-home

# Keep the production image independent from a separately copied requirements
# file. This prevents Railway build-context mistakes from failing before the
# Amosclaud source is copied into the image.
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir \
        "fastapi>=0.110,<1" \
        "uvicorn[standard]>=0.29,<1" \
        "flask>=3.0,<4" \
        "flask-cors>=4.0,<7" \
        "python-multipart>=0.0.9" \
        "python-jose[cryptography]>=3.3,<4" \
        "PyNaCl>=1.5,<2" \
        "passlib>=1.7,<2" \
        "bcrypt>=4.1,<5" \
        "jinja2>=3.1.3" \
        "bleach>=6.1,<7" \
        "markdown-it-py>=3,<5" \
        "mdit-py-plugins>=0.4,<1" \
        "webauthn>=2.2,<4" \
        "qrcode>=8,<9" \
        "anthropic>=0.25,<1" \
        "celery>=5.3,<6" \
        "redis>=5,<9" \
        "sqlalchemy>=2.0,<3" \
        "alembic>=1.13,<2" \
        "asyncpg>=0.28,<1" \
        "psycopg2-binary>=2.9.9,<3" \
        "pydantic>=2.7,<3" \
        "pydantic-settings>=2.2,<3" \
        "gitpython>=3.1,<4" \
        "click>=8.1,<9" \
        "requests>=2.31,<3" \
        "httpx>=0.27,<1" \
        "mcp>=1.27.2,<2" \
        "stripe>=11,<16" \
        "aiofiles>=23.2,<25" \
        "python-dotenv>=1.0,<2" \
        "PyYAML>=6.0,<7" \
        "dnspython>=2.6,<3" \
        "pytest>=8,<10"

COPY . /app
COPY services/workspace_runtime/workspace-image/amos /usr/local/bin/amos
RUN chmod 0755 /usr/local/bin/amos

# Fail with an explicit source-context error instead of a misleading missing
# dependency-file error.
RUN test -f /app/amoscloud_ai/main.py || (echo "Amosclaud source is missing from the Railway build context" && exit 1)

EXPOSE 8000

CMD ["sh", "-c", "uvicorn amoscloud_ai.connected_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
