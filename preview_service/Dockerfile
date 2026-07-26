# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN groupadd --gid 65532 preview \
    && useradd \
        --uid 65532 \
        --gid 65532 \
        --create-home \
        --home-dir /home/preview \
        --shell /usr/sbin/nologin \
        preview

WORKDIR /srv/amosclaud
COPY requirements.txt pyproject.toml README.md ./
COPY amoscloud_ai ./amoscloud_ai
COPY amosclaud_metrics ./amosclaud_metrics
COPY preview_service ./preview_service
RUN python -m pip install --no-cache-dir .

RUN mkdir -p /data/previews && chown -R 65532:65532 /data /srv/amosclaud
USER 65532:65532

ENV AMOSCLAUD_PREVIEW_DATA=/data/previews
EXPOSE 8080
CMD ["sh", "-c", "uvicorn preview_service.app:app --host 0.0.0.0 --port ${PORT}"]
