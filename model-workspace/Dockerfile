FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AMOSCLAUD_MODEL_HOME=/model \
    AMOSCLAUD_MODEL_HOST=0.0.0.0 \
    AMOSCLAUD_MODEL_PORT=8091

WORKDIR /app

RUN groupadd --system amosclaud && useradd --system --gid amosclaud --home-dir /model amosclaud

COPY pyproject.toml requirements.txt README.md LICENSE LICENSE-COMMERCIAL.txt ./
COPY amosclaud_model ./amosclaud_model
COPY model-workspace/config/model_metadata.json ./model_metadata.json
COPY model-workspace/datasets/curated ./bootstrap
COPY model-workspace/start-model.sh ./start-model.sh

RUN pip install --no-cache-dir . \
    && chmod 0555 /app/start-model.sh \
    && mkdir -p /model/checkpoints /model/logs /model/training/jobs \
    && chown -R amosclaud:amosclaud /model

USER amosclaud

VOLUME ["/model"]
EXPOSE 8091

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=3)" || exit 1

ENTRYPOINT ["/app/start-model.sh"]
