# amos-api-gateway/main.py
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
# Import the custom Git hosting engine router
from repository.git_server import router as git_router
# Import the autonomous codex agent engine router
from agents.codex_agent import router as agent_router
import httpx
import logging
import time

try:
    from .config import settings
    from .dependencies import get_current_user, rate_limiter
except ImportError:  # Docker starts this module as top-level `main:app`.
    from config import settings
    from dependencies import get_current_user, rate_limiter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="Amos API Gateway for microservices orchestration."
)

# Initialize HTTPX client for proxying requests
# Use a timeout to prevent hanging requests
http_client = httpx.AsyncClient(timeout=30.0, trust_env=False)

# --- Middleware for Logging ---
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    logger.info(f"Incoming request: {request.method} {request.url} from {request.client.host}")

    response = await call_next(request)

    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    logger.info(f"Outgoing response: {request.method} {request.url} - Status: {response.status_code} - Time: {process_time:.4f}s")
    return response

# --- API Gateway Routing Logic ---
async def proxy_request(request: Request, service_url: str):
    url = httpx.URL(service_url + request.url.path.replace("/api", "", 1)) # Remove /api prefix for backend
    
    # Prepare headers, removing host to prevent issues with backend services
    headers = dict(request.headers)
    headers.pop("host", None)
    
    # Forward query parameters
    params = request.query_params

    # Read request body if present
    body = await request.body() if request.method in ["POST", "PUT", "PATCH"] else None

    try:
        # Make the request to the backend service
        proxy_response = await http_client.request(
            method=request.method,
            url=url,
            headers=headers,
            params=params,
            content=body
        )

        # Create a new response with the backend's content and status
        response_headers = dict(proxy_response.headers)
        # Remove transfer-encoding header if present, as httpx handles it
        response_headers.pop("transfer-encoding", None)
        
        return Response(
            content=proxy_response.content,
            status_code=proxy_response.status_code,
            headers=response_headers,
            media_type=proxy_response.headers.get("content-type")
        )
    except httpx.RequestError as e:
        logger.error(f"Proxy request failed for {request.url} to {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service unavailable: {e}"
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred during proxying: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred."
        )

# --- Gateway Endpoints ---
# Example: Route requests starting with /api/service-a to SERVICE_A_URL
@app.api_route("/api/service-a/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def route_service_a(
    request: Request, 
    path: str, 
    current_user: dict = Depends(get_current_user), # Apply authentication
    rate_limit_ok: bool = Depends(rate_limiter) # Apply rate limiting
):
    logger.info(f"Routing to Service A for user: {current_user['username']}")
    return await proxy_request(request, settings.SERVICE_A_URL)

# Example: Route requests starting with /api/service-b to SERVICE_B_URL
@app.api_route("/api/service-b/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def route_service_b(
    request: Request, 
    path: str, 
    current_user: dict = Depends(get_current_user), # Apply authentication
    rate_limit_ok: bool = Depends(rate_limiter) # Apply rate limiting
):
    logger.info(f"Routing to Service B for user: {current_user['username']}")
    return await proxy_request(request, settings.SERVICE_B_URL)

# Example: Route requests starting with /api/service-c to SERVICE_C_URL
@app.api_route("/api/service-c/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def route_service_c(
    request: Request, 
    path: str, 
    current_user: dict = Depends(get_current_user), # Apply authentication
    rate_limit_ok: bool = Depends(rate_limiter) # Apply rate limiting
# Mount the multi-tenant Git HTTP Cloning/Pushing gateway engine
app.include_router(git_router)

# Mount the automated self-correcting Codex Agent task runtime loops
app.include_router(agent_router)

# Health check endpoint (Keep your existing lines below this)
@app.get("/health")
async def health_check():
    logger.info(f"Routing to Service C for user: {current_user['username']}")
    return await proxy_request(request, settings.SERVICE_C_URL)

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "API Gateway is running"}

# Root endpoint for documentation or general info
@app.get("/")
async def read_root():
    return JSONResponse(content={
        "message": "Welcome to Amos API Gateway",
        "version": settings.PROJECT_VERSION,
        "docs": "/docs",
        "redoc": "/redoc"
    })
