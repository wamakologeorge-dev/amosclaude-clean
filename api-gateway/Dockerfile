# amos-api-gateway/Dockerfile
# Use an official Python runtime as a parent image
FROM python:3.10-slim-buster

# Set the working directory in the container
WORKDIR /app

# Install system dependencies for cryptography (if needed, though python-jose usually handles it)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Define environment variables for the services (these can be overridden at runtime)
ENV SERVICE_A_URL="http://localhost:8001"
ENV SERVICE_B_URL="http://localhost:8002"
ENV SERVICE_C_URL="http://localhost:8003"
ENV JWT_SECRET_KEY=""

# Command to run the API Gateway
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
