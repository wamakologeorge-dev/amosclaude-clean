# Use an official Python runtime as a parent image
FROM python:3.11-slim

LABEL maintainer="Amosclaud Team"
LABEL description="Amosclaud AI - CI/CD & Deployment Automation"
LABEL version="1.0.0"

# Set the maintainer, description, and version labels
LABEL maintainer="Amosclaud Team"
LABEL description="Amosclaud AI - CI/CD & Deployment"
LABEL version="1.0.0"

# Set the working directory in the container
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the port the application will run on
EXPOSE 8000

# Run the application
CMD ["python", "-m", "uvicorn", "amoscloud_ai.main:app"]
