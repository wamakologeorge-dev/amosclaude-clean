FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md LICENSE LICENSE-COMMERCIAL.txt ./
COPY amosclaud_model ./amosclaud_model
COPY model-workspace/datasets/curated ./bootstrap
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' pydantic && pip install --no-cache-dir --no-deps .

ENV AMOSCLAUD_MODEL_HOME=/model
EXPOSE 8091
CMD ["sh", "-c", "amosclaud-model init && if [ ! -f /model/checkpoints/current.json ]; then amosclaud-model import /app/bootstrap --license project-owned && amosclaud-model train; fi && amosclaud-model serve --host 0.0.0.0 --port 8091"]
