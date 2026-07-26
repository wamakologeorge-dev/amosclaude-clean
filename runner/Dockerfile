# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        make \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 amosrunner \
    && useradd \
        --uid 65532 \
        --gid 65532 \
        --no-create-home \
        --home-dir /workspace \
        --shell /usr/sbin/nologin \
        amosrunner

ENV HOME=/workspace \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    npm_config_cache=/workspace/.npm-cache

WORKDIR /workspace
USER 65532:65532

# The worker supplies an allowlisted argument vector at runtime. The image has no
# service entrypoint and is never given the Docker socket or host credentials.
CMD ["python", "--version"]
