FROM python:3.12-slim
WORKDIR /service
RUN pip install --no-cache-dir asyncpg>=0.29,<1 httpx>=0.27,<1
COPY app ./app
CMD ["python", "-m", "app.evaluator"]
