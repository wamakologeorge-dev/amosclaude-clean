FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY amoscloud_ai/ ./amoscloud_ai/
COPY src/ ./src/
COPY web/ ./web/

EXPOSE 8000

CMD ["uvicorn", "amoscloud_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
