FROM python:3.11-slim as builder

WORKDIR /build
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim

LABEL maintainer="Amoscloud Team"
LABEL description="Amoscloud AI - CI/CD & Deployment Automation"
LABEL version="1.0.0"

WORKDIR /app

RUN apt-get update && apt-get install -y git curl libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /root/.local /root/.local

ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY . .

RUN useradd -m -u 1000 amoscloud && chown -R amoscloud:amoscloud /app
USER amoscloud

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000
CMD ["python", "-m", "amoscloud_ai.main"]
