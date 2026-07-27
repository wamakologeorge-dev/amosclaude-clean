FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/workspace-runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends acl docker.io ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/amosclaud/repositories

COPY services/workspace_runtime/requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt

COPY services/workspace_runtime/app.py ./app.py
COPY services/workspace_runtime/terminal_runtime.py ./terminal_runtime.py

EXPOSE 8080

CMD ["uvicorn", "terminal_runtime:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
