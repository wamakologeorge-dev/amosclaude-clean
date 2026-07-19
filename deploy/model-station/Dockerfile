FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AMOSCLAUD_MODEL_HOME=/data/amosclaud-model

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi uvicorn httpx pydantic

RUN mkdir -p /data/amosclaud-model

EXPOSE 8090
CMD ["sh", "-c", "uvicorn amoscloud_ai.model_station:app --host 0.0.0.0 --port ${PORT:-8090}"]
