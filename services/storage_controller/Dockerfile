FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AMOSCLAUD_STORAGE_CONTROLLER_BIND=127.0.0.1 \
    AMOSCLAUD_STORAGE_CONTROLLER_PORT=8090

WORKDIR /service

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cloud-guest-utils \
        e2fsprogs \
        fio \
        gdisk \
        nvme-cli \
        parted \
        udev \
        util-linux \
        xfsprogs \
    && rm -rf /var/lib/apt/lists/*

COPY services/storage_controller/requirements.txt /service/requirements.txt
RUN python -m pip install --no-cache-dir -r /service/requirements.txt

COPY services/storage_controller/ /service/

EXPOSE 8090

CMD ["sh", "-c", "uvicorn app:app --host ${AMOSCLAUD_STORAGE_CONTROLLER_BIND:-127.0.0.1} --port ${AMOSCLAUD_STORAGE_CONTROLLER_PORT:-8090}"]
