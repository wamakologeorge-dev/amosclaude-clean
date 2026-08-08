from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.redis.client import get_redis
from app.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await get_redis().aclose()


settings = get_settings()
app = FastAPI(title="Amosclaud Logging API", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def enforce_body_limit(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and int(length) > settings.max_event_bytes * settings.max_batch_size:
        return JSONResponse({"detail": "Request body is too large"}, status_code=413)
    return await call_next(request)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.service_name}


@app.get("/ready")
async def ready() -> dict:
    try:
        await get_redis().ping()
    except Exception as exc:
        return JSONResponse({"status": "not-ready", "reason": str(exc)}, status_code=503)
    return {"status": "ready"}
