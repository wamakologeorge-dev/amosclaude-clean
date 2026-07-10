# cmood/api-gateway/main.py
import os
import httpx
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(
    title="Amosclaud Cloud API Gateway",
    description="Production-ready API Gateway routing traffic to cmood microservices.",
    version="1.0.0"
)

# CORS Configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service Routing Map (Configurable via Environment Variables)
SERVICES = {
    "auth": os.getenv("AUTH_SERVICE_URL", "http://localhost:8001"),
    "database": os.getenv("DATABASE_SERVICE_URL", "http://localhost:8002"),
    "repository": os.getenv("REPOSITORY_SERVICE_URL", "http://localhost:8003"),
    "monitoring": os.getenv("MONITORING_SERVICE_URL", "http://localhost:8004"),
    "organization": os.getenv("ORGANIZATION_SERVICE_URL", "http://localhost:8005"),
    "amosflow": os.getenv("AMOSFLOW_SERVICE_URL", "http://localhost:8000"),
}

# Async HTTP Client for Proxying
http_client = httpx.AsyncClient(timeout=60.0)

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

async def proxy_request(service_name: str, path: str, request: Request) -> Response:
    """
    Forwards incoming requests to the designated downstream microservice.
    Preserves HTTP methods, headers, query parameters, and request body.
    """
    if service_name not in SERVICES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service_name}' is not registered at the gateway."
        )

    target_url = f"{SERVICES[service_name]}/{path}"
    
    # Extract request elements
    headers = dict(request.headers)
    # Remove Host header to prevent routing loops/errors at downstream targets
    headers.pop("host", None)
    
    params = dict(request.query_params)
    content = await request.body()
    method = request.method

    try:
        response = await http_client.request(
            method=method,
            url=target_url,
            headers=headers,
            params=params,
            content=content,
            follow_redirects=True
        )
        
        # Exclude hop-by-hop headers from downstream response
        excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
        response_headers = {
            k: v for k, v in response.headers.items() 
            if k.lower() not in excluded_headers
        }

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type")
        )

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gateway failed to connect to downstream service '{service_name}': {str(exc)}"
        )

@app.api_route("/api/v1/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def gateway_route(service: str, path: str, request: Request):
    """
    Dynamic catch-all route handler mapping path prefixes to microservices.
    Example: /api/v1/auth/login -> http://localhost:8001/login
    """
    return await proxy_request(service, path, request)

@app.get("/health")
async def gateway_health():
    """Gateway self-health check endpoint."""
    return {
        "status": "healthy",
        "gateway_time": httpx.Client().get("https://worldtimeapi.org/api/ip").json().get("datetime", None) if os.getenv("PROD") else None
    }

