# Amosclaud Model Station agent.
# Build from the repository root:
#   docker build -f station/Dockerfile -t amosclaud-station .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AMOSCLAUD_URL=https://www.amosclaud.com \
    AMOSCLAUD_STATION_BACKEND=http://127.0.0.1:11434 \
    AMOSCLAUD_STATION_MODEL=qwen2.5-coder:1.5b

WORKDIR /app

# The agent is standard library only: nothing is installed, no build tooling.
COPY station/ /app/station/

RUN useradd --create-home --uid 10001 station \
    && chown -R station:station /app
USER station

# Unhealthy while the local backend does not serve the configured model.
HEALTHCHECK --interval=30s --timeout=15s --start-period=20s --retries=3 \
    CMD ["python", "-m", "station.healthcheck"]

ENTRYPOINT ["python", "-m", "station"]
