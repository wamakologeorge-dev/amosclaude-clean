FROM python:3.12-slim
WORKDIR /service
RUN pip install --no-cache-dir redis>=5,<9 asyncpg>=0.29,<1
COPY app ./app
CMD ["python", "-m", "app.consumer"]
