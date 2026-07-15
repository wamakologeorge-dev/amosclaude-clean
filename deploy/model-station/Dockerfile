FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir fastapi uvicorn httpx pydantic

EXPOSE 8090
CMD ["uvicorn", "amoscloud_ai.model_station:app", "--host", "0.0.0.0", "--port", "8090"]
