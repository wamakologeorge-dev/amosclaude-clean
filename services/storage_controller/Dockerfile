FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /service

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cloud-guest-utils \
        e2fsprogs \
        util-linux \
        xfsprogs \
    && rm -rf /var/lib/apt/lists/*

COPY services/storage_controller/requirements.txt /service/requirements.txt
RUN python -m pip install --no-cache-dir -r /service/requirements.txt

COPY services/storage_controller/controller.py /service/controller.py

EXPOSE 8090

CMD ["uvicorn", "controller:app", "--host", "127.0.0.1", "--port", "8090"]
