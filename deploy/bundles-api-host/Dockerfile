FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AMOSCLAUD_BUNDLE_ROOT=/data/bundles

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/bundles

EXPOSE 8080
VOLUME ["/data/bundles"]
CMD ["sh", "-c", "uvicorn amoscloud_ai.bundles_host:app --host 0.0.0.0 --port ${PORT:-8080}"]
