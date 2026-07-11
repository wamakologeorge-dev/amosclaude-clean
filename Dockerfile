# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY amoscloud_ai/ ./amoscloud_ai/

# Expose the port (e.g., 8001)
EXPOSE 8001

# Set environment variables (important for production)
ENV AGENT_JWT_SECRET_KEY="your_production_agent_jwt_secret_key_here"
# ENV SQLALCHEMY_DATABASE_URL="postgresql://user:password@host:port/dbname" # For production DB

# Run the FastAPI application
CMD ["python", "-m", "amoscloud_ai.main"]
