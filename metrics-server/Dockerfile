FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md LICENSE LICENSE-COMMERCIAL.txt ./
COPY amosclaud_metrics ./amosclaud_metrics
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' httpx && pip install --no-cache-dir --no-deps .

ENV METRICS_PORT=9090
EXPOSE 9090
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9090/health', timeout=3)"
CMD ["amosclaud-metrics"]
