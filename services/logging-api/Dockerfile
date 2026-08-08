FROM python:3.12-slim
WORKDIR /service
RUN pip install --no-cache-dir fastapi>=0.115,<1 uvicorn[standard]>=0.30,<1 redis>=5,<9 pydantic-settings>=2,<3
COPY app ./app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
