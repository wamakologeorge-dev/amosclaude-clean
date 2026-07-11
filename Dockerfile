FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies using the repository-standard requirements file.
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

# Copy the API gateway into an importable Python package path.
COPY api-gateway/ ./api_gateway/

# Credentials and secrets, including AMOSCLOUD_API_TOKEN, must be supplied
# by the deployment environment rather than stored in the image.
EXPOSE 8001

CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8001"]
