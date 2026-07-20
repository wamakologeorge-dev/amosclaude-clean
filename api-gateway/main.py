"""Amosclaud API gateway joining repository, Autonomous, and CI services.

The gateway is the single authenticated ingress. It persists every Autonomous
request in the shared database and routes bounded traffic to the repository,
agent/fixer, and CI/deployment services.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from .config import settings
    from .dependencies import get_current_user, rate_limiter
except ImportError:
    from config import settings
    from dependencies import get_current_user, rate_limiter

from Amosclaud.platform_bus import PlatformByteBus, platform_bus_from_environment
from database.models import AutonomousJob, AutonomousJobStatus, Repository
from database.session import create_database, session_scope

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AmosclaudGateway")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description=(
        "Authenticated gateway for Amosclaud repositories, Autonomous repair, "
        "CI, and deployment."
    ),
)

allowed_origins = [
    item.strip()
    for item in os.getenv(
        "AMOSCLAUD_ALLOWED_ORIGINS",
        "http://www.amosclaud.com,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Amosclaud-Owner-Key",
    ],
)

http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
platform_bus: PlatformByteBus | None = None


@app.on_event("startup")
async def initialize_platform_services() -> None:
    global platform_bus
    create_database()
    platform_bus = platform_bus_from_environment()
    if platform_bus is None:
        logger.warning(
            "Internal byte bus is disabled; configure AMOSCLAUD_BYTE_BUS_SECRET"
        )
    else:
        health = platform_bus.execute(platform_bus.frame("platform.health", {})).json()
        logger.info("Internal byte bus ready: %s", health["status"])


@app.on_event("shutdown")
async def close_gateway_http_client() -> None:
    await http_client.aclose()


class ActionTask(BaseModel):
    task_id: str = Field(min_length=3, max_length=100)
    agent_type: str = Field(default="amosclaud-core", min_length=3, max_length=100)
    repository_id: int = Field(gt=0)
    objective: str = Field(min_length=3, max_length=20_000)
    target_file: str | None = Field(default=None, max_length=500)
    error_context: str | None = Field(default=None, max_length=100_000)
    payload: Dict[str, Any] = Field(default_factory=dict)


class JobStatusResponse(BaseModel):
    task_id: str
    repository_id: int
    agent_type: str
    status: str
    objective: str
    target_file: str | None
    result_summary: str | None


@app.middleware("http")
async def boundary_handshake_logging_middleware(request: Request, call_next):
    started = time.monotonic()
    logger.info("Gateway request %s %s", request.method, request.url.path)
    response: Response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.monotonic() - started:.6f}"
    response.headers["X-Amosclaud-Agent"] = "Amosclaud Autonomous"
    return response


async def forward_network_packet(
    request: Request,
    target_service_url: str,
    forwarded_path: str,
) -> Response:
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    try:
        downstream = await http_client.request(
            method=request.method,
            url=f"{target_service_url.rstrip('/')}/{forwarded_path.lstrip('/')}",
            headers=headers,
            content=body,
            params=request.query_params,
        )
        safe_headers = {
            key: value
            for key, value in downstream.headers.items()
            if key.lower()
            not in {"content-length", "transfer-encoding", "connection"}
        }
        return Response(
            content=downstream.content,
            status_code=downstream.status_code,
            headers=safe_headers,
        )
    except httpx.RequestError as exc:
        logger.error("Downstream service unavailable: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Target Amosclaud service is unavailable",
        ) from exc


def _publish_job_to_internal_bus(task_id: str) -> None:
    if platform_bus is None:
        return
    try:
        result = platform_bus.execute(
            platform_bus.frame("platform.job.status", {"task_id": task_id})
        ).json()
        logger.info(
            "Published Autonomous task %s through byte bus with status %s",
            task_id,
            result["status"],
        )
    except Exception:
        logger.exception("Failed to publish task %s through internal byte bus", task_id)


def _create_job(task: ActionTask, username: str | None = None) -> AutonomousJob:
    with session_scope() as session:
        existing = session.scalar(
            select(AutonomousJob).where(AutonomousJob.task_id == task.task_id)
        )
        if existing:
            raise HTTPException(status_code=409, detail="task_id already exists")
        repository = session.get(Repository, task.repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail="Amosclaud repository not found")
        job = AutonomousJob(
            task_id=task.task_id,
            agent_type=task.agent_type,
            repository_id=task.repository_id,
            objective=task.objective,
            target_file=task.target_file,
            error_context=task.error_context,
            status=AutonomousJobStatus.QUEUED,
            result_summary=f"Queued by {username or 'authenticated Amosclaud user'}",
        )
        session.add(job)
        session.flush()
        session.refresh(job)
    _publish_job_to_internal_bus(job.task_id)
    return job


@app.post(
    "/api/agent/run",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_agent(
    task: ActionTask,
    current_user: dict = Depends(get_current_user),
    _: bool = Depends(rate_limiter),
):
    job = _create_job(task, str(current_user.get("username", "user")))
    logger.info(
        "Queued Autonomous task %s for repository %s",
        job.task_id,
        job.repository_id,
    )
    return JobStatusResponse(
        task_id=job.task_id,
        repository_id=job.repository_id,
        agent_type=job.agent_type,
        status=job.status.value,
        objective=job.objective,
        target_file=job.target_file,
        result_summary=job.result_summary,
    )


@app.get("/api/agent/jobs/{task_id}", response_model=JobStatusResponse)
async def read_agent_job(
    task_id: str,
    _: dict = Depends(get_current_user),
    __: bool = Depends(rate_limiter),
):
    with session_scope() as session:
        job = session.scalar(
            select(AutonomousJob).where(AutonomousJob.task_id == task_id)
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Autonomous job not found")
        return JobStatusResponse(
            task_id=job.task_id,
            repository_id=job.repository_id,
            agent_type=job.agent_type,
            status=job.status.value,
            objective=job.objective,
            target_file=job.target_file,
            result_summary=job.result_summary,
        )


@app.api_route(
    "/api/repository/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def route_repository_service(
    path: str,
    request: Request,
    _: dict = Depends(get_current_user),
    __: bool = Depends(rate_limiter),
):
    return await forward_network_packet(request, settings.SERVICE_A_URL, path)


@app.api_route(
    "/api/autonomous/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def route_autonomous_service(
    path: str,
    request: Request,
    _: dict = Depends(get_current_user),
    __: bool = Depends(rate_limiter),
):
    return await forward_network_packet(request, settings.SERVICE_B_URL, path)


@app.api_route(
    "/api/ci/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def route_ci_service(
    path: str,
    request: Request,
    _: dict = Depends(get_current_user),
    __: bool = Depends(rate_limiter),
):
    return await forward_network_packet(request, settings.SERVICE_C_URL, path)


@app.get("/health")
async def health_check():
    bus_status: dict[str, Any] = {"enabled": platform_bus is not None}
    if platform_bus is not None:
        bus_status.update(
            platform_bus.execute(platform_bus.frame("platform.health", {})).json()
        )
    return {
        "status": "ok",
        "agent": "Amosclaud Autonomous",
        "database": "shared",
        "byte_bus": bus_status,
        "repository_service": settings.SERVICE_A_URL,
        "autonomous_service": settings.SERVICE_B_URL,
        "ci_service": settings.SERVICE_C_URL,
        "data-amosclaud-head": "true",
    }


@app.post(
    "/api/gateway/fixer-clone-line-auto-enject",
    response_model=JobStatusResponse,
    status_code=202,
)
async def queue_fixer_job(
    task: ActionTask,
    current_user: dict = Depends(get_current_user),
    _: bool = Depends(rate_limiter),
):
    """Queue a real repair job; never claim remediation before verification."""
    if task.agent_type == "amosclaud-core":
        task.agent_type = "amosclaud-fixer"
    job = _create_job(task, str(current_user.get("username", "user")))
    return JobStatusResponse(
        task_id=job.task_id,
        repository_id=job.repository_id,
        agent_type=job.agent_type,
        status=job.status.value,
        objective=job.objective,
        target_file=job.target_file,
        result_summary=job.result_summary,
    )


@app.exception_handler(HTTPException)
async def gateway_http_error(_: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "detail": exc.detail},
    )
