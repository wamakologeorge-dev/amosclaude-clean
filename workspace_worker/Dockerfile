FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates docker.io \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 amosclaud-worker \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin amosclaud-worker

WORKDIR /srv/amosclaud
COPY workspace_worker/requirements.txt /tmp/workspace-worker-requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/workspace-worker-requirements.txt

COPY workspace_worker /srv/amosclaud/workspace_worker

USER 10001:10001
EXPOSE 8092

CMD ["uvicorn", "workspace_worker.app:app", "--host", "0.0.0.0", "--port", "8092", "--proxy-headers", "--forwarded-allow-ips", "*"]
